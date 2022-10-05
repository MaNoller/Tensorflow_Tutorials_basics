# -*- coding: utf-8 -*-
"""Multi_worker_training_keras_tutorial.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1xKxlsq38oiAy_dLCIdpGu90CpeCWNbSX

# Overview
multi-worker distributed training with Keras model using MultiWorkerMirroredStrategy. Keras code designed to run on single machine can easily be adapted to work on mutliple workers.

## Choose Strategy
first make sure if MultiWorkerMirroredStrategy is the right choice. The common ways of distributing training w data parallelism:

*  Synchronous training: steps of training are synched across workers and replicas. all workers train over different input slices in sync and aggregate gradients at each step
*  Asynchronous training: steps not striclty synched. all workers are independently training oder input data and updating variables asynchronously.

For multi-worker synch. training without TPU, then MultiWorkerMirroredStrategy is right choice. Creates copies of all copies in models layers on each device and workers. It aggregates gradients and keeps variables in synch

# setup
"""

import json
import os
import sys

"""changes to env: in real: each worker on different machine. Here all workers on this machine. therefore: disable all gpus to prevent errors caused by workers trying to use same gpu"""

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

"""reset TF_CONFIG"""

os.environ.pop('TF_CONFIG', None)

if '.' not in sys.path:
  sys.path.insert(0, '.')

pip install tf-nightly

import tensorflow as tf

"""# Dataset and model definition
Next, create an mnist_setup.py file with a simple model and dataset setup. This Python file will be used by the worker processes in this tutorial:
"""

# Commented out IPython magic to ensure Python compatibility.
# %%writefile mnist_setup.py
# 
# import os
# import tensorflow as tf
# import numpy as np
# 
# def mnist_dataset(batch_size):
#   (x_train, y_train), _ = tf.keras.datasets.mnist.load_data()
#   # The `x` arrays are in uint8 and have values in the [0, 255] range.
#   # You need to convert them to float32 with values in the [0, 1] range.
#   x_train = x_train / np.float32(255)
#   y_train = y_train.astype(np.int64)
#   train_dataset = tf.data.Dataset.from_tensor_slices(
#       (x_train, y_train)).shuffle(60000).repeat().batch(batch_size)
#   return train_dataset
# 
# def build_and_compile_cnn_model():
#   model = tf.keras.Sequential([
#       tf.keras.layers.InputLayer(input_shape=(28, 28)),
#       tf.keras.layers.Reshape(target_shape=(28, 28, 1)),
#       tf.keras.layers.Conv2D(32, 3, activation='relu'),
#       tf.keras.layers.Flatten(),
#       tf.keras.layers.Dense(128, activation='relu'),
#       tf.keras.layers.Dense(10)
#   ])
#   model.compile(
#       loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
#       optimizer=tf.keras.optimizers.SGD(learning_rate=0.001),
#       metrics=['accuracy'])
#   return model
#

"""# Training on single worker

try on single worker to make sure all is ok

"""

import mnist_setup

batch_size = 64
single_worker_dataset = mnist_setup.mnist_dataset(batch_size)
single_worker_model = mnist_setup.build_and_compile_cnn_model()
single_worker_model.fit(single_worker_dataset, epochs=3, steps_per_epoch=70)

"""# Multi-worker configuration
### A cluster with jobs and tasks
Distributed training involves a cluster with several jobs, which again constists of one or more tasks.

TF_CONFIG is needed for training on multiple machines. It is a JSON used to specify cluster config for each worker of the cluster.

There aré two components of TF_CONFIG:
*  Cluster is same for all workers and provides information about the training cluster, which is dict if different types of jobs. 
>* with MultiWorkerMirroredStrategy there is usually one worker that has more responsibilities (checkpoints,summaries..) in addition to regular workers -> Chief worker.
>* index 0 is usually chief
*  task provides info on current task for each worker, specifies type and index of worker

example:



"""

tf_config = {
    'cluster': {
        'worker': ['localhost:12345', 'localhost:23456']
    },
    'task': {'type': 'worker', 'index': 0}
}

"""*Note that tf_config is just a local variable in Python. To use it for training configuration, serialize it as a JSON and place it in a TF_CONFIG environment variable.*"""

json.dumps(tf_config)

"""Here: type is set to worker and index to 0, so this machine will be first worker -> chief worker
*Note: Other machines will need to have the TF_CONFIG environment variable set as well, and it should have the same 'cluster' dict, but different task 'type's or task 'index'es, depending on the roles of those machines.*

in practice: create multiple workers on external IP addreses, set a TF_CONFIG for each worker. Here: two workers on localhost, the first shown above, the second (later) with tf_config['task']['index']=1

### Environment variables and subprocesses in notebooks
subprocesses inherit env vars from parent, so if one sets an env var in this notebook process
"""

os.environ['GREETINGS'] = 'Hello TensorFlow!'

"""it is accessible from the other processes:"""

!echo ${GREETINGS}

"""# Train the model
create instance of MultiWorkerMirroredStrategy

*Note: TF_CONFIG is parsed and TensorFlow's GRPC servers are started at the time MultiWorkerMirroredStrategy is called, so the TF_CONFIG environment variable must be set before a tf.distribute.Strategy instance is created. Since TF_CONFIG is not set yet, the above strategy is effectively single-worker training.*
"""

strategy = tf.distribute.MultiWorkerMirroredStrategy()

with strategy.scope():
  # Model building/compiling need to be within `strategy.scope()`.
  multi_worker_model = mnist_setup.build_and_compile_cnn_model()

"""*Note: Currently there is a limitation in MultiWorkerMirroredStrategy where TensorFlow ops need to be created after the instance of strategy is created. If you encounter RuntimeError: Collective ops must be configured at program startup, try creating the instance of MultiWorkerMirroredStrategy at the beginning of the program and put the code that may create ops after the strategy is instantiated.*

To run MultiWorkerMirroredStrategy: run worker processes and pass TF_CONFIG to them.

Here a main.py for each worker:
"""

# Commented out IPython magic to ensure Python compatibility.
# %%writefile main.py
# 
# import os
# import json
# 
# import tensorflow as tf
# import mnist_setup
# 
# per_worker_batch_size = 64
# tf_config = json.loads(os.environ['TF_CONFIG'])
# num_workers = len(tf_config['cluster']['worker'])
# 
# strategy = tf.distribute.MultiWorkerMirroredStrategy()
# 
# global_batch_size = per_worker_batch_size * num_workers
# multi_worker_dataset = mnist_setup.mnist_dataset(global_batch_size)
# 
# with strategy.scope():
#   # Model building/compiling need to be within `strategy.scope()`.
#   multi_worker_model = mnist_setup.build_and_compile_cnn_model()
# 
# 
# multi_worker_model.fit(multi_worker_dataset, epochs=3, steps_per_epoch=70)
#

"""global_batch size gets passed to dataset.batch, is set so per_worker_batch_size*num_workers. 
check cwd
"""

ls *.py

"""add TF_CONFIG to env vars"""

os.environ['TF_CONFIG'] = json.dumps(tf_config)

"""launch worker process, that will run main.py"""

# Commented out IPython magic to ensure Python compatibility.
# first kill any previous runs
# %killbgscripts

# Commented out IPython magic to ensure Python compatibility.
# %%bash --bg
# python main.py &> job_0.log

"""notice:

1. %%bash is used to run bash commands
2. --bg to run process in background, because worker will not terminate, it waits for all workers to start

backgrounded workers wont printto notebook, so put it to a file



"""

import time
time.sleep(10)

"""look at log:"""

cat job_0.log

"""log should state: Started server with target: grpc://localhost:12345, is then ready and waiting for other workers.

so: update tf_config for second worker 

"""

tf_config['task']['index'] = 1
os.environ['TF_CONFIG'] = json.dumps(tf_config)

"""launch second worker:

"""

!python main.py

"""If you recheck the logs written by the first worker, you'll learn that it participated in training that model:"""

cat job_0.log

# Commented out IPython magic to ensure Python compatibility.
# Delete the `TF_CONFIG`, and kill any background tasks so they don't affect the next section.
os.environ.pop('TF_CONFIG', None)
# %killbgscripts

"""# Duscussion
## Dataset sharding
in multi-worker training, dataset sharding is needed to ensure convergence.
In the example, the default autosharding provided by distribute.Strategy is used. this can be controlled manually by tf.data.experimental.AutoShardPolicy.
more in later tutorial

## Evaluation
if val_data is passed into model.fit, it will altenate between training and evaluation each epoch. Evaluation is distributed across workers and aggregated as well.
Validation data will also automatically be sharded. A global batch size in val_dataset and validation_steps are needed.

## Fault tolerance
in synchronous training, the cluster will fail if one worker fails and no failure-recovery is in place.

distribute.Strategy has fault tolerance when workers die. Done by preserving training state in distributed file system.
When a worker fails (pe) others will fail as well. In this case: the unavailable worker needs to be restarted.

*Note: Previously, the ModelCheckpoint callback provided a mechanism to restore the training state upon a restart from a job failure for multi-worker training. The TensorFlow team is introducing a new BackupAndRestore callback, which also adds the support to single-worker training for a consistent experience, and removed the fault tolerance functionality from existing ModelCheckpoint callback. From now on, applications that rely on this behavior should migrate to the new BackupAndRestore callback.*

### ModelCheckpoint callback
ModelCheckpoint no longer provides failt tolerance, since use BackupAndRestore

## Model saving and loading
to save, use model.save or tf.saved_model.save. The destination needs to be different for each worker.
*  non chief workers: save to temp dir
*  chief worker: save to provided model dir

The temp dirs need to be unique! -> error prevention

Model saved is identical. typically only the chief model will be used for restoring

clean temp dirs after training might be a good idea

with MultiWorkerMirroredStrategy the program is run on every worker to know who is the chief.

Below: provides file path to write, which depends on worker task_id

"""

model_path = '/tmp/keras-model'

def _is_chief(task_type, task_id):
  # Note: there are two possible `TF_CONFIG` configurations.
  #   1) In addition to `worker` tasks, a `chief` task type is use;
  #      in this case, this function should be modified to
  #      `return task_type == 'chief'`.
  #   2) Only `worker` task type is used; in this case, worker 0 is
  #      regarded as the chief. The implementation demonstrated here
  #      is for this case.
  # For the purpose of this Colab section, the `task_type` is `None` case
  # is added because it is effectively run with only a single worker.
  return (task_type == 'worker' and task_id == 0) or task_type is None

def _get_temp_dir(dirpath, task_id):
  base_dirpath = 'workertemp_' + str(task_id)
  temp_dir = os.path.join(dirpath, base_dirpath)
  tf.io.gfile.makedirs(temp_dir)
  return temp_dir

def write_filepath(filepath, task_type, task_id):
  dirpath = os.path.dirname(filepath)
  base = os.path.basename(filepath)
  if not _is_chief(task_type, task_id):
    dirpath = _get_temp_dir(dirpath, task_id)
  return os.path.join(dirpath, base)

task_type, task_id = (strategy.cluster_resolver.task_type,
                      strategy.cluster_resolver.task_id)
write_model_path = write_filepath(model_path, task_type, task_id)

"""save"""

multi_worker_model.save(write_model_path)

"""As described above, later on the model should only be loaded from the file path the chief worker saved to. Therefore, remove the temporary ones the non-chief workers have saved:"""

if not _is_chief(task_type, task_id):
  tf.io.gfile.rmtree(os.path.dirname(write_model_path))

"""Here, assume only using single worker to load and continue training, in which case you do not call tf.keras.models.load_model within another strategy.scope() (note that strategy = tf.distribute.MultiWorkerMirroredStrategy(), as defined earlier):"""

loaded_model = tf.keras.models.load_model(model_path)

# Now that the model is restored, and can continue with the training.
loaded_model.fit(single_worker_dataset, epochs=2, steps_per_epoch=20)

"""# Checkpoint saving and restoring
checkpointing allows to save weights and restore them.

Create train.Checkpoint that tracks model (managed by CHeckpointManager), so that only latest checkpoint is saved:
"""

checkpoint_dir = '/tmp/ckpt'

checkpoint = tf.train.Checkpoint(model=multi_worker_model)
write_checkpoint_dir = write_filepath(checkpoint_dir, task_type, task_id)
checkpoint_manager = tf.train.CheckpointManager(
    checkpoint, directory=write_checkpoint_dir, max_to_keep=1)

"""once set up: save and remove checkpoint of non-chief workers"""

latest_checkpoint = tf.train.latest_checkpoint(checkpoint_dir)
checkpoint.restore(latest_checkpoint)
multi_worker_model.fit(multi_worker_dataset, epochs=2, steps_per_epoch=20)

"""### BackupAndRestore callback
provides fault tolerance by backing model and curr training states

*Note: In Tensorflow 2.9, the current model and the training state is backed up at epoch boundaries. In the tf-nightly version and from TensorFlow 2.10, the BackupAndRestore callback can back up the model and the training state at epoch or step boundaries. BackupAndRestore accepts an optional save_freq argument. save_freq accepts either 'epoch' or an int value. If save_freq is set to 'epoch' the model is backed up after every epoch. If save_freq is set to an integer value greater than 0, the model is backed up after every save_freq number of batches.*

once job is interrupted ans restarted, backupandrestore restores last checkpoint. To use it: provide instance of backupandrestore at the model.fit call

With multiworkermirroredstrategy, is a worker gets interrupted, the whole cluster will pause until the worker is restarted. other workers will also restart and interrupted worker rejoins cluster. -> back in synch.

Currently, the BackupAndRestore callback supports single-worker training with no strategy—MirroredStrategy—and multi-worker training with MultiWorkerMirroredStrategy.

Below are two examples for both multi-worker training and single-worker training:

"""

# Multi-worker training with `MultiWorkerMirroredStrategy`
# and the `BackupAndRestore` callback. The training state 
# is backed up at epoch boundaries by default.

callbacks = [tf.keras.callbacks.BackupAndRestore(backup_dir='/tmp/backup')]
with strategy.scope():
  multi_worker_model = mnist_setup.build_and_compile_cnn_model()
multi_worker_model.fit(multi_worker_dataset,
                       epochs=3,
                       steps_per_epoch=70,
                       callbacks=callbacks)

"""If the save_freq argument in the BackupAndRestore callback is set to 'epoch', the model is backed up after every epoch."""

# The training state is backed up at epoch boundaries because `save_freq` is
# set to `epoch`.

callbacks = [tf.keras.callbacks.BackupAndRestore(backup_dir='/tmp/backup')]
with strategy.scope():
  multi_worker_model = mnist_setup.build_and_compile_cnn_model()
multi_worker_model.fit(multi_worker_dataset,
                       epochs=3,
                       steps_per_epoch=70,
                       callbacks=callbacks)

"""Note: The next code block uses features that are only available in tf-nightly until Tensorflow 2.10 is released.

If the save_freq argument in the BackupAndRestore callback is set to an integer value greater than 0, the model is backed up after every save_freq number of batches.
"""

# The training state is backed up at every 30 steps because `save_freq` is set
# to an integer value of `30`.

callbacks = [tf.keras.callbacks.BackupAndRestore(backup_dir='/tmp/backup', save_freq=30)]
with strategy.scope():
  multi_worker_model = mnist_setup.build_and_compile_cnn_model()
multi_worker_model.fit(multi_worker_dataset,
                       epochs=3,
                       steps_per_epoch=70,
                       callbacks=callbacks)