"""
    Building model, training and testing over MNIST data
"""

from __future__ import print_function
import timeit
import gzip
import copy
import numpy
import math
import theano
import theano.tensor as T
from logistic_regression import LogisticRegression
from hidden_layer import HiddenLayer
from loading_data import load_mnist_data, load_cifar_data
from conv_layers import LeNetConvPoolLayer, MyConvPoolLayer, MyConvLayer


def evaluate_mnist(learning_rate=0.1, n_epochs=100,
                    dataset='mnist.pkl.gz',
                    nkerns=[20, 50, 60], batch_size=32, 
                    L2_coeff=0.0001):
    """ Network for classification of MNIST database

    :type learning_rate: float
    :param learning_rate: this is the initial learning rate used
                            (factor for the stochastic gradient)

    :type n_epochs: int
    :param n_epochs: maximal number of epochs to run the optimizer

    :type dataset: string
    :param dataset: path to the dataset used for training /testing (MNIST here)

    :type nkerns: list of ints
    :param nkerns: number of kernels on each layer

    :type batch_size: int
    :param batch_size: the batch size for training

    :type L2_coeff: float
    :param L2_coeff: the L2 regularization coefficient used in the loss function
    """

    rng = numpy.random.RandomState(23455)

    # loading the mnist data
    datasets = load_mnist_data(dataset)
    train_set_x, train_set_y = datasets[0]
    valid_set_x, valid_set_y = datasets[1]
    test_set_x, test_set_y = datasets[2]

    # compute number of minibatches for training, validation and testing
    n_train_batches = train_set_x.get_value(borrow=True).shape[0]
    n_valid_batches = valid_set_x.get_value(borrow=True).shape[0]
    n_test_batches = test_set_x.get_value(borrow=True).shape[0]
    n_train_batches //= batch_size
    n_valid_batches //= batch_size
    n_test_batches //= batch_size

    # allocate symbolic variables for the data
    index = T.lscalar()  # index to a [mini]batch

    # start-snippet-1
    x = T.matrix('x')   # the data is presented as rasterized images
    y = T.ivector('y')  # the labels are presented as 1D vector of
                        # [int] labels

    ######################
    # BUILD ACTUAL MODEL #
    ######################
    print('Building the model...')

    # Reshape matrix of rasterized images of shape (batch_size, 28 * 28)
    # to a 4D tensor, compatible with our LeNetConvPoolLayer
    # (28, 28) is the size of MNIST images.
    layer0_input = x.reshape((batch_size, 1, 28, 28))

    # Construct the first convolutional pooling layer:
    # filtering reduces the image size to (28-5+1 , 28-5+1) = (24, 24)
    # maxpooling reduces this further to (24/2, 24/2) = (12, 12)
    # 4D output tensor is thus of shape (batch_size, nkerns[0], 12, 12)
    layer0 = LeNetConvPoolLayer(
        rng,
        input=layer0_input,
        image_shape=(batch_size, 1, 28, 28),
        filter_shape=(nkerns[0], 1, 5, 5),
        poolsize=(2, 2)
    )

    # Construct the second convolutional pooling layer
    # filtering reduces the image size to (12-5+1, 12-5+1) = (8, 8)
    # maxpooling reduces this further to (8/2, 8/2) = (4, 4)
    # 4D output tensor is thus of shape (batch_size, nkerns[1], 4, 4)
    layer1 = LeNetConvPoolLayer(
        rng,
        input=layer0.output,
        image_shape=(batch_size, nkerns[0], 12, 12),
        filter_shape=(nkerns[1], nkerns[0], 5, 5),
        poolsize=(2, 2)
    )

    # Construct the third convolutional layer
    # filtering reduces the image size to (4-3+1, 4-3+1) = (2, 2)
    # 4D output tensor is thus of shape (batch_size, nkerns[2], 2, 2)
    layer2 = MyConvLayer(
        rng,
        input = layer1.output,
        image_shape = (batch_size, nkerns[1], 4, 4),
        filter_shape=(nkerns[2], nkerns[1], 3, 3),
    )

    # the HiddenLayer being fully-connected, it operates on 2D matrices of
    # shape (batch_size, num_pixels) (i.e matrix of rasterized images).
    # This will generate a matrix of shape (batch_size, nkerns[2] * 2 * 2),
    # or (500, 60 * 2 * 2) = (500, 240) with the default values.
    layer3_input = layer2.output.flatten(2)

    # construct a fully-connected sigmoidal layer
    layer3 = HiddenLayer(
        rng,
        input=layer3_input,
        n_in=nkerns[2] * 2 * 2,
        n_out=500,
        activation=T.tanh
    )

    # classify the values of the fully-connected sigmoidal layer
    layer4 = LogisticRegression(input=layer3.output, n_in=500, n_out=10)

    # the cost we minimize during training is the NLL of the model
    # cost = layer4.negative_log_likelihood(y)
    cost = layer4.negative_log_likelihood(y) + L2_coeff * (layer0.L2_sqr + layer1.L2_sqr + layer2.L2_sqr + layer3.L2_sqr + layer4.L2_sqr)

    # create a function to compute the mistakes that are made by the model
    test_model = theano.function(
        [index],
        layer4.errors(y),
        givens={
            x: test_set_x[index * batch_size: (index + 1) * batch_size],
            y: test_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )

    validate_model = theano.function(
        [index],
        layer4.errors(y),
        givens={
            x: valid_set_x[index * batch_size: (index + 1) * batch_size],
            y: valid_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )

    # create a list of all model parameters to be fit by gradient descent
    params = layer4.params + layer3.params + layer2.params + layer1.params + layer0.params

    # create a list of gradients for all model parameters
    grads = T.grad(cost, params)

    # the learning rate for batch SGD (adaptive learning rate)
    l_rate = T.scalar('l_rate', dtype=theano.config.floatX)

    # train_model is a function that updates the model parameters by
    # SGD Since this model has many parameters, it would be tedious to
    # manually create an update rule for each model parameter. We thus
    # create the updates list by automatically looping over all
    # (params[i], grads[i]) pairs.
    updates = [
        (param_i, param_i - l_rate * grad_i)
        for param_i, grad_i in zip(params, grads)
    ]

    train_model = theano.function(
        [index, l_rate],
        cost,
        updates=updates,
        givens={
            x: train_set_x[index * batch_size: (index + 1) * batch_size],
            y: train_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )
    # end-snippet-1

    ###############
    # TRAIN MODEL #
    ###############
    print('Training...')
    # early-stopping parameters
    patience = 50000  # look as this many examples regardless
    patience_increase = 2  # wait this much longer when a new best is
                           # found
    improvement_threshold = 0.995  # a relative improvement of this much is
                                   # considered significant
    validation_frequency = min(n_train_batches, patience // 2)
                                  # go through this many
                                  # minibatche before checking the network
                                  # on the validation set; in this case we
                                  # check every epoch

    best_validation_loss = numpy.inf
    best_iter = 0
    test_score = 0.
    start_time = timeit.default_timer()

    epoch = 0
    done_looping = False

    # initializing the adaptive leaning rate
    adaptive_learning_rate = learning_rate

    while (epoch < n_epochs) and (not done_looping):
        epoch = epoch + 1

        if epoch % 10 == 0:
            # decreasing the learning rate after every 10 epochs
            adaptive_learning_rate = 0.95*adaptive_learning_rate
            
        for minibatch_index in range(n_train_batches):

            iter = (epoch - 1) * n_train_batches + minibatch_index

            if iter % 100 == 0:
                print('training @ iter = ', iter)
            cost_ij = train_model(minibatch_index, adaptive_learning_rate)

            if (iter + 1) % validation_frequency == 0:

                # compute zero-one loss on validation set
                validation_losses = [validate_model(i) for i
                                     in range(n_valid_batches)]
                this_validation_loss = numpy.mean(validation_losses)
                print('epoch %i, minibatch %i/%i, validation error %f %%' %
                      (epoch, minibatch_index + 1, n_train_batches,
                       this_validation_loss * 100.))

                # if we got the best validation score until now
                if this_validation_loss < best_validation_loss:
                    
                    # increase the learning rate by small amount (adaptive)
                    adaptive_learning_rate = 1.01 * adaptive_learning_rate

                    #improve patience if loss improvement is good enough
                    if this_validation_loss < best_validation_loss *  \
                       improvement_threshold:
                        patience = max(patience, iter * patience_increase)

                    # save best validation score and iteration number
                    best_validation_loss = this_validation_loss
                    best_iter = iter

                    # test it on the test set
                    test_losses = [
                        test_model(i)
                        for i in range(n_test_batches)
                    ]
                    test_score = numpy.mean(test_losses)
                    print(('     epoch %i, minibatch %i/%i, test error of '
                           'best model %f %%') %
                          (epoch, minibatch_index + 1, n_train_batches,
                           test_score * 100.))

                else:
                    # decrease the learning rate by small amount (adaptive)
                    adaptive_learning_rate = 0.5 * adaptive_learning_rate

            if patience <= iter:
                done_looping = True
                break

    end_time = timeit.default_timer()
    print('Optimization complete.')
    print('Best validation score of %f %% obtained at iteration %i, '
          'with test performance %f %%' %
          (best_validation_loss * 100., best_iter + 1, test_score * 100.))
    print(('The code for file ' +
           os.path.split(__file__)[1] +
           ' ran for %.2fm' % ((end_time - start_time) / 60.)), file=sys.stderr)