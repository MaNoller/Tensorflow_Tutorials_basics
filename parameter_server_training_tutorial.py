# -*- coding: utf-8 -*-
"""parameter_server_training_tutorial.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1YvyQQO8cuoSKhD1HzdzIoUEZJ5Mej5xw

# General
parameter server training is a data parallel method to scale training on multiple machines.

Parameter server training clusters consist of workers and parameter servers. Variables are created on param server and get read/updated by workers in each step. By default the workers to this independently without synching. -> asynch training.

## Supported training methods
two main methods:
*  keras model.fit
*  custom training loop

##Cluster with jobs and tasks
distributed training in TF2 involves a cluster with several jobs with several tasks. With param server training it is recommendet to have:
*  One coordinator job (job name chief)
*  Multiple worker jobs (job name worker)
*  multiple parameter server jobs (job name ps)
Where the coordinator creates resources, dispatches tasks, writes checkpoints and deals w failures. Workers and param servers run distribute.Server instances that listen to coordinator.

##Parameter server training w Model.fit
requires coordinator to use distribute.ParameterServerStrategy object.

##Parameter server training with custom training loop
with custom training loops, tf.distribute.coordinator.ClusterCoordinator is used for coordinator.
*  ClusterCoordinator work with a distribute.Strategyy obj
*  distribution.Strategy obj provides info of the cluster and define training step
*  ClusterCoordinator dispatches execution of training to workers
*  for server param training, ClusterCoordinator needs distribute.ParameterServerStrategy

schedule is key component:
*  schedule enqueues tf.function and returns a RemoteValue
*  queued fcns are dispatched to workers in background threads and RemoteValue will be filles asynch
*  schedule does not need worker assignment, tf.function can be executed on any available worker
*  worker unavailable while execution, so retried on other workers

CLusterCoordinator also helps create datasets on workers and rebuilds them in case of failure

#Setup
"""

pip install portpicker

import multiprocessing
import os
import random
import portpicker
import tensorflow as tf



"""# Cluster Setup
a param server training cluster requires a coodinator, at least one worker and parameter server tasls that run TF servers and maybe an additional evaluation server that runr sidecar evaluation. Requirements for setup:
*  coordinator needs to know addresses and ports of all servers, except evaluator
*  workers and param servers need to know which port to listen to
*  eval task does not need to know setup of cluster
*  workers and parama servers should have task types "worker"/"ps". Cooridnator "chief"

###In-process Cluster
start by creating several servers and connect them later. note: ONLY for tutorial here, in reality: servers started on "worker" ond "ps" machines
"""

def create_in_process_cluster(num_workers, num_ps):
  """Creates and starts local servers and returns the cluster_resolver."""
  worker_ports = [portpicker.pick_unused_port() for _ in range(num_workers)]
  ps_ports = [portpicker.pick_unused_port() for _ in range(num_ps)]

  cluster_dict = {}
  cluster_dict["worker"] = ["localhost:%s" % port for port in worker_ports]
  if num_ps > 0:
    cluster_dict["ps"] = ["localhost:%s" % port for port in ps_ports]

  cluster_spec = tf.train.ClusterSpec(cluster_dict)

  # Workers need some inter_ops threads to work properly.
  worker_config = tf.compat.v1.ConfigProto()
  if multiprocessing.cpu_count() < num_workers + 1:
    worker_config.inter_op_parallelism_threads = num_workers + 1

  for i in range(num_workers):
    tf.distribute.Server(
        cluster_spec,
        job_name="worker",
        task_index=i,
        config=worker_config,
        protocol="grpc")

  for i in range(num_ps):
    tf.distribute.Server(
        cluster_spec,
        job_name="ps",
        task_index=i,
        protocol="grpc")

  cluster_resolver = tf.distribute.cluster_resolver.SimpleClusterResolver(
      cluster_spec, rpc_layer="grpc")
  return cluster_resolver

# Set the environment variable to allow reporting worker and ps failure to the
# coordinator. This is a workaround and won't be necessary in the future.
os.environ["GRPC_FAIL_FAST"] = "use_caller"

NUM_WORKERS = 3
NUM_PS = 2
cluster_resolver = create_in_process_cluster(NUM_WORKERS, NUM_PS)

"""#Instantiate ParameterServerStrategy
this is needed for both model.fit and custom training loop.
To use GPU for training, allocate all gpus visible to all workers. parameterserverstrategy will use them all on each worker.
"""

variable_partitioner = (
    tf.distribute.experimental.partitioners.MinSizePartitioner(
        min_shard_bytes=(256 << 10),
        max_shards=NUM_PS))

strategy = tf.distribute.ParameterServerStrategy(
    cluster_resolver,
    variable_partitioner=variable_partitioner)

"""##Variable sharding
refers to splitting variable into multiple smaller variables, called shards. may be usefull to distribute network load and computation/storage on workers.

To enable var sharding, pass variable_partitioner into parameterserverstrategy. it will be invoked every time a variable is created and returns the num of shards along each dim of variable.

When variable_partitioner is passed in and a variable directly under Strategy.scope is created, the variable will become container type with variables property, which provides aacces to list of shards. Most of times, this will be autoconverted to a Tensor by concatenating all shards -> can be used as normal variable

#Training w Model.fit
model.fit is easy to use training api, that handles the training loop,  with overridable train_step and callbacks that provide checkpointing etc

##input data
model.fit with parameterserverstrategy can take input in form of dataset (recommended), distributeddataset or datasetcreator. When encountering memory issues with dataset, datasetcreator is recommended with dataset_fn arg

when transforming dataset to tf.data.dataset, it is recommended to use Dataset.shuffle and Dataset.repeat
*  model.fit w param server training assumes each worker receioves same dataset, except when shuffled differently. With shuffle ensure more even iterations over the data
*  because workers are not synch, they may finish processing at different times. Define epoch by dataset.repeat - which repeats dataset indefinitely when without arg  


"""

global_batch_size = 64

x = tf.random.uniform((10, 10))
y = tf.random.uniform((10,))

dataset = tf.data.Dataset.from_tensor_slices((x, y)).shuffle(10).repeat()
dataset = dataset.batch(global_batch_size)
dataset = dataset.prefetch(2)

"""# Model construction and compiling"""

with strategy.scope():
  model = tf.keras.models.Sequential([tf.keras.layers.Dense(10)])

  model.compile(tf.keras.optimizers.SGD(), loss="mse", steps_per_execution=10)

"""# callbacks and training
before training: prepare callbacks for:
*  ModelCheckpoint: saved at certain frequency
*  BackupAndRestore: backing up model and epoch number. enables restoration and continuation (?)
*  TensorBoard: writes model logs
"""

working_dir = "/tmp/my_working_dir"
log_dir = os.path.join(working_dir, "log")
ckpt_filepath = os.path.join(working_dir, "ckpt")
backup_dir = os.path.join(working_dir, "backup")

callbacks = [
    tf.keras.callbacks.TensorBoard(log_dir=log_dir),
    tf.keras.callbacks.ModelCheckpoint(filepath=ckpt_filepath),
    tf.keras.callbacks.BackupAndRestore(backup_dir=backup_dir),
]

model.fit(dataset, epochs=5, steps_per_epoch=20, callbacks=callbacks)

"""# Training with custom training loop
custom loops with distribute.Strategy provide great flexibility for defining loops. With ParameterServerSTrategy, one can use a ClusterCoordinator to dispatch execution of training steps to remote workers.

# Set up the data
firstly, a fcn that creates the dataset.if the data should be preprocessed with keras preprocessing layers or transform layers, create these outsite the dateset_fn and under Strategy.scope, like for any other keras layers. Reason: dataset_fn will be wrapped in a tf.function and then excecuted on each worker to generate data pipeline.

Other procedures might cause slowdown. Placing them under strategy.scope will create them on all workers, then transform inside the dataset_fn. Refere to distributed input tutorial for further information.
"""

feature_vocab = [
    "avenger", "ironman", "batman", "hulk", "spiderman", "kingkong", "wonder_woman"
]
label_vocab = ["yes", "no"]

with strategy.scope():
  feature_lookup_layer = tf.keras.layers.StringLookup(
      vocabulary=feature_vocab,
      mask_token=None)
  label_lookup_layer = tf.keras.layers.StringLookup(
      vocabulary=label_vocab,
      num_oov_indices=0,
      mask_token=None)

  raw_feature_input = tf.keras.layers.Input(
      shape=(3,),
      dtype=tf.string,
      name="feature")
  feature_id_input = feature_lookup_layer(raw_feature_input)
  feature_preprocess_stage = tf.keras.Model(
      {"features": raw_feature_input},
      feature_id_input)

  raw_label_input = tf.keras.layers.Input(
      shape=(1,),
      dtype=tf.string,
      name="label")
  label_id_input = label_lookup_layer(raw_label_input)

  label_preprocess_stage = tf.keras.Model(
      {"label": raw_label_input},
      label_id_input)

"""generate examples in a dataset"""

def feature_and_label_gen(num_examples=200):
  examples = {"features": [], "label": []}
  for _ in range(num_examples):
    features = random.sample(feature_vocab, 3)
    label = ["yes"] if "avenger" in features else ["no"]
    examples["features"].append(features)
    examples["label"].append(label)
  return examples

examples = feature_and_label_gen()

"""create training dataset wrapped in a dataset_fcn:"""

def dataset_fn(_):
  raw_dataset = tf.data.Dataset.from_tensor_slices(examples)

  train_dataset = raw_dataset.map(
      lambda x: (
          {"features": feature_preprocess_stage(x["features"])},
          label_preprocess_stage(x["label"])
      )).shuffle(200).batch(32).repeat()
  return train_dataset

"""# build model
make sure to create all variables under strategy.scope
"""

# These variables created under the `Strategy.scope` will be placed on parameter
# servers in a round-robin fashion.
with strategy.scope():
  # Create the model. The input needs to be compatible with Keras processing layers.
  model_input = tf.keras.layers.Input(
      shape=(3,), dtype=tf.int64, name="model_input")

  emb_layer = tf.keras.layers.Embedding(
      input_dim=len(feature_lookup_layer.get_vocabulary()), output_dim=16384)
  emb_output = tf.reduce_mean(emb_layer(model_input), axis=1)
  dense_output = tf.keras.layers.Dense(units=1, activation="sigmoid")(emb_output)
  model = tf.keras.Model({"features": model_input}, dense_output)

  optimizer = tf.keras.optimizers.RMSprop(learning_rate=0.1)
  accuracy = tf.keras.metrics.Accuracy()

"""confirm that FicedShardsPartitioner split all variables"""

assert len(emb_layer.weights) == 2
assert emb_layer.weights[0].shape == (4, 16384)
assert emb_layer.weights[1].shape == (4, 16384)

print(emb_layer.weights[0].device)
print(emb_layer.weights[1].device)

"""# Define training step"""

@tf.function
def step_fn(iterator):

  def replica_fn(batch_data, labels):
    with tf.GradientTape() as tape:
      pred = model(batch_data, training=True)
      per_example_loss = tf.keras.losses.BinaryCrossentropy(
          reduction=tf.keras.losses.Reduction.NONE)(labels, pred)
      loss = tf.nn.compute_average_loss(per_example_loss)
      gradients = tape.gradient(loss, model.trainable_variables)

    optimizer.apply_gradients(zip(gradients, model.trainable_variables))

    actual_pred = tf.cast(tf.greater(pred, 0.5), tf.int64)
    accuracy.update_state(labels, actual_pred)
    return loss

  batch_data, labels = next(iterator)
  losses = strategy.run(replica_fn, args=(batch_data, labels))
  return strategy.reduce(tf.distribute.ReduceOp.SUM, losses, axis=None)

"""Strategy.run and Strategy.reduce in the step_fn can support multiple GPUs per worker. If the workers have GPUs allocated, Strategy.run will distribute the datasets on multiple replicas.

# Dispatching training to remote workers

after computations are defined by parameterserverstrategy, Clustercooridnator will distribute the training stept wo workers
"""

coordinator = tf.distribute.coordinator.ClusterCoordinator(strategy)

"""create per-worker dataset"""

@tf.function
def per_worker_dataset_fn():
  return strategy.distribute_datasets_from_function(dataset_fn)

per_worker_dataset = coordinator.create_per_worker_dataset(per_worker_dataset_fn)
per_worker_iterator = iter(per_worker_dataset)

"""finally, distribute via schedule. Schedule ebqueues a tf.function and returns RemoteValue. The queues fcns will be dispatched to remote workers and remotevalue will be filled asynch., With join, wait untill all scheduled fcns are executed"""

num_epochs = 4
steps_per_epoch = 5
for i in range(num_epochs):
  accuracy.reset_states()
  for _ in range(steps_per_epoch):
    coordinator.schedule(step_fn, args=(per_worker_iterator,))
  # Wait at epoch boundaries.
  coordinator.join()
  print("Finished epoch %d, accuracy is %f." % (i, accuracy.result().numpy()))

"""fetch result of RemoteValue"""

loss = coordinator.schedule(step_fn, args=(per_worker_iterator,))
print("Final loss is %f" % loss.fetch())

"""# Evaluation
## Inline Evaluation
here, the coordinator alternates between training and evaluation. Benefits are:
*  support large eval models and datasets
*  eval results can be used to make decisions for next epoch

the main ways to implement: direct and distributed.
###direct evaluation
for small models and datasets. Coordinator runs eal directly on distributed model.
"""

eval_dataset = tf.data.Dataset.from_tensor_slices(
    feature_and_label_gen(num_examples=16)).map(
          lambda x: (
              {"features": feature_preprocess_stage(x["features"])},
              label_preprocess_stage(x["label"])
          )).batch(8)

eval_accuracy = tf.keras.metrics.Accuracy()

for batch_data, labels in eval_dataset:
  pred = model(batch_data, training=False)
  actual_pred = tf.cast(tf.greater(pred, 0.5), tf.int64)
  eval_accuracy.update_state(labels, actual_pred)

print("Evaluation accuracy: %f" % eval_accuracy.result())

"""###distributed evaluation:
for large models and datasets. The evaluation is distributed to the workers:
"""

with strategy.scope():
  # Define the eval metric on parameter servers.
  eval_accuracy = tf.keras.metrics.Accuracy()

@tf.function
def eval_step(iterator):
  def replica_fn(batch_data, labels):
    pred = model(batch_data, training=False)
    actual_pred = tf.cast(tf.greater(pred, 0.5), tf.int64)
    eval_accuracy.update_state(labels, actual_pred)
  batch_data, labels = next(iterator)
  strategy.run(replica_fn, args=(batch_data, labels))

def eval_dataset_fn():
  return tf.data.Dataset.from_tensor_slices(
      feature_and_label_gen(num_examples=16)).map(
          lambda x: (
              {"features": feature_preprocess_stage(x["features"])},
              label_preprocess_stage(x["label"])
          )).shuffle(16).repeat().batch(8)

per_worker_eval_dataset = coordinator.create_per_worker_dataset(eval_dataset_fn)
per_worker_eval_iterator = iter(per_worker_eval_dataset)

eval_steps_per_epoch = 2
for _ in range(eval_steps_per_epoch):
  coordinator.schedule(eval_step, args=(per_worker_eval_iterator,))
coordinator.join()
print("Evaluation accuracy: %f" % eval_accuracy.result())

"""## Sidecar evaluation
here, a dedicated evaluator task repeatedly reads checkpoints and runs evals on them. so requires additional evaluator task and periodic checkpointing.

Two options here:
* Use SidecarEvaluator
* create custom evaluation loop

Sidecar eval is only supported with single task:
*  each example is guaranteed to be evaluated once
*  full evaluation might take some time
*  if size too big, single evaluator might not be epplicable

A custom evaluation loop provides more control over the details, such as choosing which checkpoint to evaluate, or providing any additional logic to run along with evaluation. The following is a possible custom sidecar evaluation loop:
"""

checkpoint_dir = ...
eval_model = ...
eval_data = ...
checkpoint = tf.train.Checkpoint(model=eval_model)

for latest_checkpoint in tf.train.checkpoints_iterator(
    checkpoint_dir):
  try:
    checkpoint.restore(latest_checkpoint).expect_partial()
  except (tf.errors.OpError,) as e:
    # checkpoint may be deleted by training when it is about to read it.
    continue

  # Optionally add callbacks to write summaries.
  eval_model.evaluate(eval_data)

  # Evaluation finishes when it has evaluated the last epoch.
  if latest_checkpoint.endswith('-{}'.format(train_epochs)):
    break

"""# Clusters in the real world

in reality, the tasks will run in different processes on different machines. simplest way is tp set a TF_CONFIG env var and use tf.distribute.cluster_resolver.TFConfigClusterResolver for parsing it.

###Set TF_CONFIG env var
example: 3 workers and 2 param servers, then TF_CONFIG of worker 1 can be:
"""

os.environ["TF_CONFIG"] = json.dumps({
    "cluster": {
        "worker": ["host1:port", "host2:port", "host3:port"],
        "ps": ["host4:port", "host5:port"],
        "chief": ["host6:port"]
    },
    "task": {"type": "worker", "index": 1}
})

"""for the evaluator would be"""

os.environ["TF_CONFIG"] = json.dumps({
    "cluster": {
        "evaluator": ["host7:port"]
    },
    "task": {"type": "evaluator", "index": 0}
})

"""###the same binary for all tasks:
If you prefer to run all these tasks using a single binary, you will need to let your program branch into different roles at the very beginning:
"""

cluster_resolver = tf.distribute.cluster_resolver.TFConfigClusterResolver()
if cluster_resolver.task_type in ("worker", "ps"):
  # Start a TensorFlow server and wait.
elif cluster_resolver.task_type == "evaluator":
  # Run sidecar evaluation
else:
  # Run the coordinator.

"""following starts a sever and waits"""

# Set the environment variable to allow reporting worker and ps failure to the
# coordinator. This is a workaround and won't be necessary in the future.
os.environ["GRPC_FAIL_FAST"] = "use_caller"

server = tf.distribute.Server(
    cluster_resolver.cluster_spec(),
    job_name=cluster_resolver.task_type,
    task_index=cluster_resolver.task_id,
    protocol=cluster_resolver.rpc_layer or "grpc",
    start=True)
server.join()

"""# Task failure
## parameter server or coordinator failure
when the coordinator  encounters a param server error, it will raise an UnavailableError or AbortedError. -> Restart coordinator. If coordinator unavailable, this wont work, so:
*  for model.fit, use backupansrestore callback
*  for custom loop, checkpoint model and variables periodically and load from checkpoint.  The training progress can be inferred approximately from optimizer.iterations if an optimizer is checkpointed:
"""

checkpoint_manager = tf.train.CheckpointManager(
    tf.train.Checkpoint(model=model, optimizer=optimizer),
    checkpoint_dir,
    max_to_keep=3)
if checkpoint_manager.latest_checkpoint:
  checkpoint = checkpoint_manager.checkpoint
  checkpoint.restore(
      checkpoint_manager.latest_checkpoint).assert_existing_objects_matched()

global_steps = int(optimizer.iterations.numpy())
starting_epoch = global_steps // steps_per_epoch

for _ in range(starting_epoch, num_epochs):
  for _ in range(steps_per_epoch):
    coordinator.schedule(step_fn, args=(per_worker_iterator,))
  coordinator.join()
  checkpoint_manager.save()

"""### Fetching remoteValue
Fetching a RemoteValue is guaranteed to succeed if a function is executed successfully. This is because currently the return value is immediately copied to the coordinator after a function is executed. If there is any worker failure during the copy, the function will be retried on another available worker. Therefore, if you want to optimize for performance, you can schedule functions without a return value.

# Performance Improvement
One common reason for performance issues is ab unbalanced load on param servers, or reached capacity on param servers. To mitigate:
*  shard large model variables via variable_partitioner
*  avoid creating hotspot variables that is required by all param servers in a single step
*shuffle large vocabularies before passing them to preprocessing layers
"""