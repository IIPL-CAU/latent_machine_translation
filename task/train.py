# Import modules
import os
import gc
import psutil
import pickle
import logging
from tqdm import tqdm
from time import time
# Import PyTorch
import torch
from torch.nn import functional as F
from torch.utils.data import DataLoader
from torch.nn.utils import clip_grad_norm_
from torch.cuda.amp import GradScaler, autocast
from torch.utils.tensorboard import SummaryWriter
# Import custom modules
from model.dataset import CustomDataset
from model.custom_transformer.transformer import Transformer
from model.plm.bart import Bart
from model.loss import label_smoothing_loss
from optimizer.utils import shceduler_select, optimizer_select
from utils import TqdmLoggingHandler, write_log, get_tb_exp_name

def training(args):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    #===================================#
    #==============Logging==============#
    #===================================#

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    handler = TqdmLoggingHandler()
    handler.setFormatter(logging.Formatter(" %(asctime)s - %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False

    if args.use_tensorboard:
        writer = SummaryWriter(os.path.join(args.tensorboard_path, get_tb_exp_name(args)))
        writer.add_text('args', str(args))

    write_log(logger, 'Start training!')

    #===================================#
    #============Data Load==============#
    #===================================#

    # 1) Data open
    write_log(logger, "Load data...")
    gc.disable()

    save_path = os.path.join(args.preprocess_path, args.tokenizer)
    if args.tokenizer == 'spm':
        save_name = f'processed_{args.data_name}_{args.sentencepiece_model}_src_{args.src_vocab_size}_trg_{args.trg_vocab_size}.pkl'
    else:
        save_name = f'processed_{args.data_name}_{args.tokenizer}.pkl'

    with open(os.path.join(save_path, save_name), 'rb') as f:
        data_ = pickle.load(f)
        train_src_indices = data_['train_src_indices']
        valid_src_indices = data_['valid_src_indices']
        train_src_att_mask = data_['train_src_att_mask']
        valid_src_att_mask = data_['valid_src_att_mask']
        train_trg_indices = data_['train_trg_indices']
        valid_trg_indices = data_['valid_trg_indices']
        train_trg_att_mask = data_['train_src_att_mask']
        valid_trg_att_mask = data_['valid_src_att_mask']
        src_word2id = data_['src_word2id']
        trg_word2id = data_['trg_word2id']
        src_vocab_num = len(src_word2id)
        trg_vocab_num = len(trg_word2id)
        del data_
    gc.enable()
    write_log(logger, "Finished loading data!")

    # 2) Dataloader setting
    dataset_dict = {
        'train': CustomDataset(src_list=train_src_indices, trg_list=train_trg_indices, 
                            src_att_mask_list=train_src_att_mask, trg_att_mask_list=train_trg_att_mask,
                            min_len=args.min_len, src_max_len=args.src_max_len, trg_max_len=args.trg_max_len),
        'valid': CustomDataset(src_list=valid_src_indices, trg_list=valid_trg_indices,
                            src_att_mask_list=valid_src_att_mask, trg_att_mask_list=valid_trg_att_mask,
                            min_len=args.min_len, src_max_len=args.src_max_len, trg_max_len=args.trg_max_len),
    }
    dataloader_dict = {
        'train': DataLoader(dataset_dict['train'], drop_last=True,
                            batch_size=args.batch_size, shuffle=True, pin_memory=True,
                            num_workers=args.num_workers),
        'valid': DataLoader(dataset_dict['valid'], drop_last=False,
                            batch_size=args.batch_size, shuffle=False, pin_memory=True,
                            num_workers=args.num_workers)
    }
    write_log(logger, f"Total number of trainingsets  iterations - {len(dataset_dict['train'])}, {len(dataloader_dict['train'])}")

    #===================================#
    #===========Train setting===========#
    #===================================#

    # 1) Model initiating
    write_log(logger, 'Instantiating model...')
    if args.model_type == 'custom_transformer':
        model = Transformer(src_vocab_num=src_vocab_num, trg_vocab_num=trg_vocab_num,
                            pad_idx=args.pad_id, bos_idx=args.bos_id, eos_idx=args.eos_id,
                            d_model=args.d_model, d_embedding=args.d_embedding, n_head=args.n_head,
                            dim_feedforward=args.dim_feedforward,
                            num_common_layer=args.num_common_layer, num_encoder_layer=args.num_encoder_layer,
                            num_decoder_layer=args.num_decoder_layer,
                            src_max_len=args.src_max_len, trg_max_len=args.trg_max_len,
                            dropout=args.dropout, embedding_dropout=args.embedding_dropout,
                            trg_emb_prj_weight_sharing=args.trg_emb_prj_weight_sharing,
                            emb_src_trg_weight_sharing=args.emb_src_trg_weight_sharing, 
                            variational=args.variational, parallel=args.parallel)
        tgt_subsqeunt_mask = model.generate_square_subsequent_mask(args.trg_max_len - 1, device)
    else:
        model = Bart(isPreTrain=args.isPreTrain, variational=args.variational, d_latent=args.d_latent,
                     emb_src_trg_weight_sharing=args.emb_src_trg_weight_sharing)
        tgt_subsqeunt_mask = model.generate_square_subsequent_mask(args.trg_max_len - 1, device)
    model = model.to(device)
    
    # 2) Optimizer & Learning rate scheduler setting
    optimizer = optimizer_select(model, args)
    scheduler = shceduler_select(optimizer, dataloader_dict, args)
    scaler = GradScaler()

    # 3) Model resume
    start_epoch = 0
    if args.resume:
        write_log(logger, 'Resume model...')
        checkpoint = torch.load(os.path.join(args.save_path, 'checkpoint.pth.tar'))
        start_epoch = checkpoint['epoch'] + 1
        model.load_state_dict(checkpoint['model'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        scheduler.load_state_dict(checkpoint['scheduler'])
        scaler.load_state_dict(checkpoint['scaler'])
        del checkpoint

    #===================================#
    #=========Model Train Start=========#
    #===================================#

    best_val_acc = 0

    write_log(logger, 'Traing start!')

    for epoch in range(start_epoch + 1, args.num_epochs + 1):
        start_time_e = time()
        for phase in ['train', 'valid']:
            if phase == 'train':
                model.train()
            if phase == 'valid':
                write_log(logger, 'Validation start...')
                val_loss = 0
                val_acc = 0
                model.eval()
            for i, (src, src_att, trg, trg_att) in enumerate(tqdm(dataloader_dict[phase], bar_format='{l_bar}{bar:30}{r_bar}{bar:-2b}')):

                # Optimizer setting
                optimizer.zero_grad(set_to_none=True)

                # Input, output setting
                src = src.to(device, non_blocking=True)
                src_att = src_att.to(device, non_blocking=True)
                trg = trg.to(device, non_blocking=True)
                trg_att = trg_att.to(device, non_blocking=True)

                trg_target = trg[:, 1:]
                non_pad = trg_target != args.pad_id
                trg_target = trg_target[non_pad].contiguous().view(-1)

                # Train
                if phase == 'train':

                    with autocast():
                        predicted, kl = model(
                            src, src_att, trg, trg_att, non_pad_position=non_pad, tgt_subsqeunt_mask=tgt_subsqeunt_mask)
                        predicted = predicted.view(-1, predicted.size(-1))
                        nmt_loss = label_smoothing_loss(predicted, trg_target, trg_pad_idx=args.pad_id)
                        total_loss = nmt_loss + kl

                    scaler.scale(total_loss).backward()
                    if args.clip_grad_norm > 0:
                        scaler.unscale_(optimizer)
                        clip_grad_norm_(model.parameters(), args.clip_grad_norm)
                    scaler.step(optimizer)
                    scaler.update()

                    if args.scheduler in ['constant', 'warmup']:
                        scheduler.step()
                    if args.scheduler == 'reduce_train':
                        scheduler.step(nmt_loss)

                    # Print loss value only training
                    if i == 0 or freq == args.print_freq or i==len(dataloader_dict['train']):
                        acc = (predicted.max(dim=1)[1] == trg_target).sum() / len(trg_target)
                        iter_log = "[Epoch:%03d][%03d/%03d] train_loss:%03.3f | train_acc:%03.2f%% | learning_rate:%1.6f | spend_time:%02.2fmin" % \
                            (epoch, i, len(dataloader_dict['train']), 
                            total_loss.item(), acc*100, optimizer.param_groups[0]['lr'], 
                            (time() - start_time_e) / 60)
                        write_log(logger, iter_log)
                        freq = 0
                    freq += 1

                    if args.use_tensorboard:
                        acc = (predicted.max(dim=1)[1] == trg_target).sum() / len(trg_target)
                        
                        writer.add_scalar('TRAIN/Loss', total_loss.item(), (epoch-1) * len(dataloader_dict['train']) + i)
                        writer.add_scalar('TRAIN/Accuracy', acc*100, (epoch-1) * len(dataloader_dict['train']) + i)
                        writer.add_scalar('CPU_Usage', psutil.cpu_percent(), (epoch-1) * len(dataloader_dict['train']) + i)
                        writer.add_scalar('RAM_Usage', psutil.virtual_memory().percent, (epoch-1) * len(dataloader_dict['train']) + i)
                        writer.add_scalar('GPU_Usage', torch.cuda.memory_allocated() / 1048576, (epoch-1) * len(dataloader_dict['train']) + i) # MB Size

                # Validation
                if phase == 'valid':
                    with torch.no_grad():
                        predicted, kl = model(
                            src, src_att, trg, trg_att, non_pad_position=non_pad, tgt_subsqeunt_mask=tgt_subsqeunt_mask)
                        nmt_loss = F.cross_entropy(predicted, trg_target)
                        total_loss = nmt_loss + kl
                    val_loss += total_loss.item()
                    val_acc += (predicted.max(dim=1)[1] == trg_target).sum() / len(trg_target)
                    if args.scheduler == 'reduce_valid':
                        scheduler.step(val_loss)
                    if args.scheduler == 'lambda':
                        scheduler.step()

            if phase == 'valid':
                val_loss /= len(dataloader_dict[phase])
                val_acc /= len(dataloader_dict[phase])
                write_log(logger, 'This version is variational kl criterion dim=0 version')
                write_log(logger, 'Validation Loss: %3.3f' % val_loss)
                write_log(logger, 'Validation Accuracy: %3.2f%%' % (val_acc * 100))
                save_file_name = os.path.join(args.save_path, 
                                              f'checkpoint_{args.data_name}_p_{args.parallel}_v_{args.variational}.pth.tar')
                if val_acc > best_val_acc:
                    write_log(logger, 'Checkpoint saving...')
                    torch.save({
                        'epoch': epoch,
                        'model': model.state_dict(),
                        'optimizer': optimizer.state_dict(),
                        'scheduler': scheduler.state_dict(),
                        'scaler': scaler.state_dict()
                    }, save_file_name)
                    best_val_acc = val_acc
                    best_epoch = epoch
                else:
                    else_log = f'Still {best_epoch} epoch accuracy({round(best_val_acc.item()*100, 2)})% is better...'
                    write_log(logger, else_log)

                if args.use_tensorboard:
                    writer.add_scalar('VALID/Loss', val_loss, epoch)
                    writer.add_scalar('VALID/Accuracy', val_acc * 100, epoch)
                    #writer.add_scalar('CPU_Usage', psutil.cpu_percent(), epoch)
                    #writer.add_scalar('RAM_Usage', psutil.virtual_memory().percent, epoch)
                    #writer.add_scalar('GPU_Usage', torch.cuda.memory_allocated() / 1048576, epoch) # MB Size

    # 3) Print results
    print(f'Best Epoch: {best_epoch}')
    print(f'Best Accuracy: {round(best_val_acc.item(), 2)}')