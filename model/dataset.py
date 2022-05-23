import torch
from torch.utils.data.dataset import Dataset

class Seq2SeqDataset(Dataset):
    def __init__(self, src_list, src_att_list, trg_list, trg_att_list,
                 min_len: int = 4, src_max_len: int = 300, trg_max_len: int = 360):
        self.tensor_list = []
        for src, src_att, trg, trg_att in zip(src_list, src_att_list, trg_list, trg_att_list):
            if min_len <= len(src) <= src_max_len and min_len <= len(trg) <= trg_max_len:
                # Source tensor
                src_tensor = torch.zeros(src_max_len, dtype=torch.long)
                src_tensor[:len(src)] = torch.tensor(src, dtype=torch.long)
                src_att_tensor = torch.tensor(src_att, dtype=torch.long)
                # Target tensor
                trg_tensor = torch.zeros(trg_max_len, dtype=torch.long)
                trg_tensor[:len(trg)] = torch.tensor(trg, dtype=torch.long)
                trg_att_tensor = torch.tensor(trg_att, dtype=torch.long)
                #
                self.tensor_list.append((src_tensor, src_att_tensor, trg_tensor, trg_att_tensor))

        self.num_data = len(self.tensor_list)

    def __getitem__(self, index):
        return self.tensor_list[index]

    def __len__(self):
        return self.num_data

class Seq2LabelDataset(Dataset):
    def __init__(self, src_list, src_att_list, trg_list,
                 min_len: int = 4, src_max_len: int = 300):
        self.tensor_list = []
        for src, src_att, trg in zip(src_list, src_att_list, trg_list):
            if min_len <= len(src) <= src_max_len:
                # Source tensor
                src_tensor = torch.zeros(src_max_len, dtype=torch.long)
                src_tensor[:len(src)] = torch.tensor(src, dtype=torch.long)
                src_att_tensor = torch.tensor(src_att, dtype=torch.long)
                # Target tensor
                trg_tensor = torch.tensor(trg, dtype=torch.long)
                #
                self.tensor_list.append((src_tensor, src_att_tensor, trg_tensor))

        self.num_data = len(self.tensor_list)

    def __getitem__(self, index):
        return self.tensor_list[index]

    def __len__(self):
        return self.num_data