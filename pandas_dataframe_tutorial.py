# -*- coding: utf-8 -*-
"""pandas_dataframe_tutorial.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/130_ynZIVDkFOm9AB-alc2ZvEV8T587k4
"""

import pandas as pd
import tensorflow as tf

SHUFFLE_BUFFER = 500
BATCH_SIZE = 2

csv_file = tf.keras.utils.get_file('heart.csv', 'https://storage.googleapis.com/download.tensorflow.org/data/heart.csv')

df = pd.read_csv(csv_file)

df.head()

df.dtypes

"""prediction target: !target"""

target = df.pop('target')

"""# Dataframe as an array

is data in uniform datatype, one can use a pd df anywhere where s np array is applicable. pd.df supports __array__ and tf.convert_to_tensor accepts these objects

take numerical features
"""

numeric_feature_names = ['age', 'thalach', 'trestbps',  'chol', 'oldpeak']
numeric_features = df[numeric_feature_names]
numeric_features.head()

"""The df can be converted to np array usind DataFrame.values. to convert it to tensor, use tf.convert_to_tensor."""

tf.convert_to_tensor(numeric_features)

"""### with model.fit

A Dataframe, interpreted as single tensor, can be used as arg in Model.fit.

Firstly, normalization of input
"""

normalizer = tf.keras.layers.Normalization(axis=-1)
normalizer.adapt(numeric_features)

normalizer(numeric_features.iloc[:3])

"""Simple model:"""

def get_basic_model():
  model = tf.keras.Sequential([
    normalizer,
    tf.keras.layers.Dense(10, activation='relu'),
    tf.keras.layers.Dense(10, activation='relu'),
    tf.keras.layers.Dense(1)
  ])

  model.compile(optimizer='adam',
                loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
                metrics=['accuracy'])
  return model

"""When you pass the DataFrame as the x argument to Model.fit, Keras treats the DataFrame as it would a NumPy array:"""

model = get_basic_model()
model.fit(numeric_features, target, epochs=15, batch_size=BATCH_SIZE)

"""### With tf.data

if tf.apply is to be used to DF of uniform dtype, Dataset.from_tensor_slices will create dataset, that iterates over the rows of the DF. To train a model, (inputs,labels) pairs are needes, so (features, labels) will be oassed and Dataset.from_tensor_slices returns pairs of slices
"""

numeric_dataset = tf.data.Dataset.from_tensor_slices((numeric_features, target))

for row in numeric_dataset.take(3):
  print(row)

numeric_batches = numeric_dataset.shuffle(1000).batch(BATCH_SIZE)

model = get_basic_model()
model.fit(numeric_batches, epochs=15)

"""# Dataframe as dict

When the data is heterogeneous, the DF cannot be used as array. TF tensors need all elements to be same dtype.

so, use it as dict of columns, each column of dtype.

tf.data input pipelines can do this. 
"""

numeric_dict_ds = tf.data.Dataset.from_tensor_slices((dict(numeric_features), target))

for row in numeric_dict_ds.take(3):
  print(row)

"""### Dict with Keras

Keras expect a single input tensor, but can accept nested structs as well, known as "nests" (tf.nest).

There are two ways to do that:

1) The Model-subclass

You write a subclass of tf.keras.Model (or tf.keras.Layer). You directly handle the inputs, and create the outputs:
"""

def stack_dict(inputs, fun=tf.stack):
    values = []
    for key in sorted(inputs.keys()):
      values.append(tf.cast(inputs[key], tf.float32))

    return fun(values, axis=-1)

class MyModel(tf.keras.Model):
  def __init__(self):
    # Create all the internal layers in init.
    super().__init__(self)

    self.normalizer = tf.keras.layers.Normalization(axis=-1)

    self.seq = tf.keras.Sequential([
      self.normalizer,
      tf.keras.layers.Dense(10, activation='relu'),
      tf.keras.layers.Dense(10, activation='relu'),
      tf.keras.layers.Dense(1)
    ])

  def adapt(self, inputs):
    # Stack the inputs and `adapt` the normalization layer.
    inputs = stack_dict(inputs)
    self.normalizer.adapt(inputs)

  def call(self, inputs):
    # Stack the inputs
    inputs = stack_dict(inputs)
    # Run them through all the layers.
    result = self.seq(inputs)

    return result

model = MyModel()

model.adapt(dict(numeric_features))

model.compile(optimizer='adam',
              loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
              metrics=['accuracy'],
              run_eagerly=True)

"""This model can accept either a dictionary of columns or a dataset of dictionary-elements for training:"""

model.fit(dict(numeric_features), target, epochs=5, batch_size=BATCH_SIZE)

numeric_dict_batches = numeric_dict_ds.shuffle(SHUFFLE_BUFFER).batch(BATCH_SIZE)
model.fit(numeric_dict_batches, epochs=5)

model.predict(dict(numeric_features.iloc[:3]))

"""2) Keras functional style"""

inputs = {}
for name, column in numeric_features.items():
  inputs[name] = tf.keras.Input(
      shape=(1,), name=name, dtype=tf.float32)

inputs

x = stack_dict(inputs, fun=tf.concat)

normalizer = tf.keras.layers.Normalization(axis=-1)
normalizer.adapt(stack_dict(dict(numeric_features)))

x = normalizer(x)
x = tf.keras.layers.Dense(10, activation='relu')(x)
x = tf.keras.layers.Dense(10, activation='relu')(x)
x = tf.keras.layers.Dense(1)(x)

model = tf.keras.Model(inputs, x)

model.compile(optimizer='adam',
              loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
              metrics=['accuracy'],
              run_eagerly=True)

tf.keras.utils.plot_model(model, rankdir="LR", show_shapes=True)

model.fit(dict(numeric_features), target, epochs=5, batch_size=BATCH_SIZE)

numeric_dict_batches = numeric_dict_ds.shuffle(SHUFFLE_BUFFER).batch(BATCH_SIZE)
model.fit(numeric_dict_batches, epochs=5)

"""# Full Example
When working with heterogeneous data, each column may need unique preprocessing. This needs to be done the same way for all inputs, which can be achieved by using keras preprocessing layers

### Build preprocessing head
Here, some of the int features are actually categorical and need to be encoded. the same goes for string-categorical. Binary does not need to be encoded or normalized

Create list of features for groups:
"""

binary_feature_names = ['sex', 'fbs', 'exang']

categorical_feature_names = ['cp', 'restecg', 'slope', 'thal', 'ca']

"""next, build preprocessing model. Start by creating tf.keras.Input for each column"""

inputs = {}
for name, column in df.items():
  if type(column[0]) == str:
    dtype = tf.string
  elif (name in categorical_feature_names or
        name in binary_feature_names):
    dtype = tf.int64
  else:
    dtype = tf.float32

  inputs[name] = tf.keras.Input(shape=(), name=name, dtype=dtype)

inputs

"""each input will be transformed in one way. "Each feature starts as a batch of scalars (shape=(batch,)). The output for each should be a batch of tf.float32 vectors (shape=(batch, n)). The last step will concatenate all those vectors together."

### Binary inputs
Binary dont need preprocessing, so just add to axis, cast them to float32 and add to list of preprocessed inputs:
"""

preprocessed = []

for name in binary_feature_names:
  inp = inputs[name]
  inp = inp[:, tf.newaxis]
  float_value = tf.cast(inp, tf.float32)
  preprocessed.append(float_value)

preprocessed

"""### Numeric inputs

Numeric data should be normalized. Additionally, they will be input as a dict. below collects num features,stacks them and passes to normalize.adapt
"""

normalizer = tf.keras.layers.Normalization(axis=-1)
normalizer.adapt(stack_dict(dict(numeric_features)))

"""stack features and normalize:"""

numeric_inputs = {}
for name in numeric_feature_names:
  numeric_inputs[name]=inputs[name]

numeric_inputs = stack_dict(numeric_inputs)
numeric_normalized = normalizer(numeric_inputs)

preprocessed.append(numeric_normalized)

preprocessed

"""### Categorical Inputs

Categoricals have to be encoded into binary vectors or embeddings. Here: convert to one-hot vectors, since only small num of categories

example:
"""

vocab = ['a','b','c']
lookup = tf.keras.layers.StringLookup(vocabulary=vocab, output_mode='one_hot')
lookup(['c','a','a','b','zzz'])

vocab = [1,4,7,99]
lookup = tf.keras.layers.IntegerLookup(vocabulary=vocab, output_mode='one_hot')

lookup([-1,4,1])

"""determine the voc fpr input: create voc to one-hot vector"""

for name in categorical_feature_names:
  vocab = sorted(set(df[name]))
  print(f'name: {name}')
  print(f'vocab: {vocab}\n')

  if type(vocab[0]) is str:
    lookup = tf.keras.layers.StringLookup(vocabulary=vocab, output_mode='one_hot')
  else:
    lookup = tf.keras.layers.IntegerLookup(vocabulary=vocab, output_mode='one_hot')

  x = inputs[name][:, tf.newaxis]
  x = lookup(x)
  preprocessed.append(x)

"""### assemble preprocessing 

the preprocessed is just a list with all the preprocessing results in shape (batch_size, depth)
"""

preprocessed

"""concatenate all features along depth axis, so dict-example is converted to single vector containing all the features"""

preprocesssed_result = tf.concat(preprocessed, axis=-1)
preprocesssed_result

"""create model"""

preprocessor = tf.keras.Model(inputs, preprocesssed_result)

tf.keras.utils.plot_model(preprocessor, rankdir="LR", show_shapes=True)

"""### Create and train model"""

body = tf.keras.Sequential([
  tf.keras.layers.Dense(10, activation='relu'),
  tf.keras.layers.Dense(10, activation='relu'),
  tf.keras.layers.Dense(1)
])

inputs

x = preprocessor(inputs)
x

result = body(x)
result

model = tf.keras.Model(inputs, result)

model.compile(optimizer='adam',
                loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
                metrics=['accuracy'])

"""This model expects a dict of inputs. Best way: convert df to dictt and pass to model.fit"""

history = model.fit(dict(df), target, epochs=5, batch_size=BATCH_SIZE)