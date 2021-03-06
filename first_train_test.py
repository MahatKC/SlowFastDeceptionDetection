import time, gc, os

import pandas as pd
import numpy as np
from datetime import datetime
from os.path import exists
from torch.utils.tensorboard import SummaryWriter
from sklearn.metrics import confusion_matrix

import mxnet as mx
from mxnet import gluon
from mxnet import autograd as ag

from gluoncv.data.transforms import video
from gluoncv.data import VideoClsCustom
from gluoncv.model_zoo import get_model
from gluoncv.utils import split_and_load

def save_to_csv(execution_id, learning_rate, lr_decay_strategy, optimizer, weight_decay, network, epochs, acc, val_acc):
    results_df = pd.DataFrame({
        'execution_id': [str(execution_id)],
        'learning_rate' : [str(learning_rate)],
        'lr_decay_strategy': [str(lr_decay_strategy)],
        'optimizer': [optimizer],
        'wd': [str(weight_decay)],
        'network': [network],
        'epochs': [str(epochs)],
        'training_acc': [str(acc)],
        'val_acc': [str(val_acc)]
    })

    if exists("hyperparameter_search.csv"):
        file_df = pd.read_csv("hyperparameter_search.csv")
        file_df = pd.concat([file_df,results_df], ignore_index=True)
        file_df.to_csv("hyperparameter_search.csv",index=False)
    else:
        results_df.to_csv("hyperparameter_search.csv",index=False)
    
    pass

def train_network(execution_id, ctx, network, epochs, lr_decay_epoch, optimizer, learning_rate, weight_decay):
    net = get_model(name=network, nclass=2)
    net.collect_params().reset_ctx(ctx)

    lr_decay = 0.1

    if optimizer=='sgd':
        optimizer_params = {'learning_rate': learning_rate, 'wd': weight_decay, 'momentum': 0.9} 
    else:
        #Using standard beta1, beta2 and epsilon for Adam and standard gamma1 and gamma2 for RMSProp
        optimizer_params = {'learning_rate': learning_rate, 'wd': weight_decay} 

    trainer = gluon.Trainer(net.collect_params(), optimizer, optimizer_params)
    loss_fn = gluon.loss.SoftmaxCrossEntropyLoss()

    train_metric = mx.metric.Accuracy()
    val_metric = mx.metric.Accuracy()
    test_metric = mx.metric.Accuracy()
    writer = SummaryWriter(log_dir='runs/run'+str(execution_id))

    lr_decay_count = 0

    for epoch in range(epochs):
        tic = time.time()
        train_metric.reset()
        train_loss = 0

        # Learning rate decay
        if epoch == lr_decay_epoch[lr_decay_count]:
            trainer.set_learning_rate(trainer.learning_rate*lr_decay)
            lr_decay_count += 1

        # Loop through each batch of training data
        for i, batch in enumerate(train_data):
            # Extract data and label
            data = split_and_load(batch[0], ctx_list=ctx, batch_axis=0)
            label = split_and_load(batch[1], ctx_list=ctx, batch_axis=0)

            # AutoGrad
            with ag.record():
                output = []
                for _, X in enumerate(data):
                    X = X.reshape((-1,) + X.shape[2:])
                    pred = net(X)
                    output.append(pred)
                loss = [loss_fn(yhat, y) for yhat, y in zip(output, label)]

            # Backpropagation
            for l in loss:
                l.backward()

            # Optimize
            trainer.step(batch_size)

            # Update metrics
            train_loss += sum([l.mean().asscalar() for l in loss])
            train_metric.update(label, output)
        
        #Get validation accuracy
        for i, batch in enumerate(val_data):
            data = split_and_load(batch[0], ctx_list=ctx, batch_axis=0)
            label = split_and_load(batch[1], ctx_list=ctx, batch_axis=0)
            
            output = []
            for _, X in enumerate(data):
                X = X.reshape((-1,) + X.shape[2:])
                pred = net(X)
                output.append(pred)
            
            val_metric.update(label, output)

        name, acc = train_metric.get()
        name, val_acc = val_metric.get()

        # Update Tensorboard
        writer.add_scalar('Accuracy/train', acc, epoch)
        writer.add_scalar('Accuracy/val', val_acc, epoch)

        if epoch%20==0:
            print(f'[Epoch {epoch}] train={acc} val={val_acc} loss={train_loss/(i+1)} time: {time.time()-tic}')

    #Get test accuracy
    for i, batch in enumerate(test_data):
        data = split_and_load(batch[0], ctx_list=ctx, batch_axis=0)
        label = split_and_load(batch[1], ctx_list=ctx, batch_axis=0)
        
        output = []
        for _, X in enumerate(data):
            X = X.reshape((-1,) + X.shape[2:])
            pred = net(X)
            output.append(pred)
        
        test_metric.update(label, output)

    name, test_acc = test_metric.get()
    print(f"RUN {execution_id} Test acc={test_acc}")

    save_to_csv(execution_id, learning_rate, lr_decay_epoch, optimizer, weight_decay, network, epochs, acc, val_acc)

    writer.close()
    writer.flush()

    pass

def train_5_fold_network(execution_id, ctx, network, epochs, lr_decay_epoch, optimizer, learning_rate, weight_decay, train_data, test_data):
    net = get_model(name=network, nclass=2)
    net.collect_params().reset_ctx(ctx)

    lr_decay = 0.1

    optimizer_params = {'learning_rate': learning_rate, 'wd': weight_decay, 'momentum': 0.9} 

    trainer = gluon.Trainer(net.collect_params(), optimizer, optimizer_params)
    loss_fn = gluon.loss.SoftmaxCrossEntropyLoss()

    train_metric = mx.metric.Accuracy()
    test_metric = mx.metric.Accuracy()

    lr_decay_count = 0

    for epoch in range(epochs):
        tic = time.time()
        train_metric.reset()
        train_loss = 0

        # Learning rate decay
        if epoch == lr_decay_epoch[lr_decay_count]:
            trainer.set_learning_rate(trainer.learning_rate*lr_decay)
            lr_decay_count += 1

        # Loop through each batch of training data
        for i, batch in enumerate(train_data):
            # Extract data and label
            data = split_and_load(batch[0], ctx_list=ctx, batch_axis=0)
            label = split_and_load(batch[1], ctx_list=ctx, batch_axis=0)

            # AutoGrad
            with ag.record():
                output = []
                for _, X in enumerate(data):
                    X = X.reshape((-1,) + X.shape[2:])
                    pred = net(X)
                    output.append(pred)
                loss = [loss_fn(yhat, y) for yhat, y in zip(output, label)]

            # Backpropagation
            for l in loss:
                l.backward()

            # Optimize
            trainer.step(batch_size)

            # Update metrics
            train_loss += sum([l.mean().asscalar() for l in loss])
            train_metric.update(label, output)
        
        name, acc = train_metric.get()

    all_labels = []
    all_outputs = []

    #Get test accuracy
    for i, batch in enumerate(test_data):
        data = split_and_load(batch[0], ctx_list=ctx, batch_axis=0)
        label = split_and_load(batch[1], ctx_list=ctx, batch_axis=0)
        
        output = []
        for _, X in enumerate(data):
            X = X.reshape((-1,) + X.shape[2:])
            pred = net(X)
            output.append(pred)
        
        for l in label:
            all_labels.extend(l.asnumpy().tolist())

        for o in output[0]:
            all_outputs.append(np.argmax(o.asnumpy()))
        
        test_metric.update(label, output)

    cm = confusion_matrix(all_labels, all_outputs)

    name, test_acc = test_metric.get()
    print(f"Train acc= {acc} Test acc={test_acc}")

    return test_acc, cm

def load_train_val_test(length):
    transform_train = video.VideoGroupTrainTransform(size=(224, 224), scale_ratios=[1.0, 0.8], mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    
    train_dataset = VideoClsCustom(root=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/Clips'),
                                setting=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/train.txt'),
                                train=True,
                                new_length=length,
                                video_loader=True,
                                slowfast = True,
                                use_decord=True,
                                transform=transform_train)
    val_dataset = VideoClsCustom(root=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/Clips'),
                                setting=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/val.txt'),
                                train=False,
                                new_length=length,
                                video_loader=True,
                                slowfast = True,
                                use_decord=True,
                                transform=transform_train)
                
    test_dataset = VideoClsCustom(root=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/Clips'),
                                setting=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/test.txt'),
                                train=False,
                                new_length=length,
                                video_loader=True,
                                slowfast = True,
                                use_decord=True,
                                transform=transform_train)

    train_data = gluon.data.DataLoader(train_dataset, batch_size=batch_size,
                                    shuffle=True, num_workers=num_workers)
    val_data = gluon.data.DataLoader(val_dataset, batch_size=batch_size,
                                    shuffle=True, num_workers=num_workers)
    test_data = gluon.data.DataLoader(test_dataset, batch_size=batch_size,
                                    shuffle=True, num_workers=num_workers)

    return train_data, val_data, test_data

def load_folds(fold_index, length):
    transform_train = video.VideoGroupTrainTransform(size=(224, 224), scale_ratios=[1.0, 0.8], mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    
    #UNCOMMENT THIS FOR FIRST RUN
    #filenames = ['foldB_0.txt', 'foldB_1.txt', 'foldB_2.txt', 'foldB_3.txt', 'foldB_4.txt']
    #with open('Real-life_Deception_Detection_2016/train_with_foldB_'+str(fold_index)+'_as_test.txt', 'w') as outfile:
    #    for fname in filenames:
    #        if fname == 'foldB_'+str(fold_index)+'.txt':
    #            continue
    #        else:
    #            with open('Real-life_Deception_Detection_2016/'+fname) as infile:
    #                for line in infile:
    #                    outfile.write(line)
    #                outfile.write('\n')

    train_dataset = VideoClsCustom(root=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/Clips'),
                                setting=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/train_with_foldB_'+str(fold_index)+'_as_test.txt'),
                                train=True,
                                new_length=length,
                                video_loader=True,
                                slowfast = True,
                                use_decord=True,
                                transform=transform_train)
                
    test_dataset = VideoClsCustom(root=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/Clips'),
                                setting=os.path.expanduser('/home/petcomp/TCC Mahat/Projeto/Real-life_Deception_Detection_2016/foldB_'+str(fold_index)+'.txt'),
                                train=False,
                                new_length=length,
                                video_loader=True,
                                slowfast = True,
                                use_decord=True,
                                transform=transform_train)

    train_data = gluon.data.DataLoader(train_dataset, batch_size=batch_size,
                                    shuffle=True, num_workers=num_workers)
    test_data = gluon.data.DataLoader(test_dataset, batch_size=batch_size,
                                    shuffle=True, num_workers=num_workers)

    return train_data, test_data

def train_5_fold(execution_id, ctx, network, num_epochs, lr_decay_strategy, chosen_optimizer, lr, weight_decay):
    final_test_acc = 0
    execution_id *= 100
    print(datetime.now())
    with open('5FoldResults.txt', 'a') as results:
        results.write('\nRun '+str(execution_id)+"\n")
        for i in range(5):
            train_data, test_data = load_folds(i, 64)
            test_acc, cm = train_5_fold_network(execution_id+i, ctx, network, num_epochs, lr_decay_strategy, chosen_optimizer, lr, weight_decay, train_data, test_data)
            ctx[0].empty_cache()
            gc.collect() 
            final_test_acc += test_acc
            results.write('------Fold '+str(i)+" | Acuracia: "+str(test_acc)+'\n')
            results.write(str(cm))
            results.write('\n')

        results.write("ACURACIA FINAL: "+str(final_test_acc/5)+'\n')
    print(f"ACURACIA FINAL: {final_test_acc/5}")

num_gpus = 1
ctx = [mx.gpu(i) for i in range(num_gpus)]
per_device_batch_size = 1
num_workers = 1
batch_size = per_device_batch_size * num_gpus

lr_decay_strategy = [[10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 300], [40, 80, 100, 300]]

network = 'slowfast_4x16_resnet50_kinetics400'
chosen_optimizer = 'sgd'

params = [[ 8,100,0,0.0001, 0.001],
          [11,100,0,0.0001,0.0005],
          [ 6,100,1,0.0001, 0.005],
          [65,200,0,0.0001, 0.001],
          [67,200,1,0.0001, 0.005]
         ]


for id, epochs, strat, wd, lr in params:
    print(f'BEGINNING RUN {id}')
    print('-'*20)
    decay_strat = lr_decay_strategy[strat]
    train_5_fold(id, ctx, network, epochs, decay_strat, chosen_optimizer, lr, wd)