from tqdm import tqdm
from toolz.functoolz import compose
from torch.utils.data import Dataset
from sklearn.preprocessing import LabelEncoder


class LMDataset(Dataset):
    """Wraps a wikitext dataset from pytorch
    NLP which is provided as a list of tokens
    """

    def __init__(self, tokens, max_len=256):
        self.max_len = max_len

        self.data = [
            self._split_samples(tokens, idx)
            for idx in tqdm(range(len(tokens) - 1), total=len(tokens) - 1)
        ]
        self.transforms = []

    def _split_samples(self, tokens, idx):
        _len = min(self.max_len, len(tokens) - 1 - idx)
        inputs = tokens[idx : idx + _len]
        targets = tokens[idx + 1 : idx + 1 + _len]
        return inputs, targets

    def map(self, fn, lazy=True):
        self.transforms.append(fn)
        if not lazy:
            self.apply_transforms()
        return self

    def apply_transforms(self):
        fn = compose(*self.transforms[::-1])
        self.transforms = []
        # In place transformation to save some mem.
        for i in tqdm(range(len(self.data)), total=len(self.data)):
            self.data[i] = (fn(self.data[i][0]), fn(self.data[i][1]))
        return self

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        datum = self.data[idx]
        for t in self.transforms:
            datum = t(datum)
        return datum


class ClassificationCorpus(Dataset):
    def __init__(self, corpus, labels):
        self.corpus = corpus
        self.labels = labels
        assert len(self.labels) == len(self.corpus), "Incompatible labels and corpus"
        self.transforms = []
        self.label_encoder = LabelEncoder().fit(self.labels)

    def map(self, t):
        self.transforms.append(t)
        return self

    def __len__(self):
        return len(self.corpus)

    def __getitem__(self, idx):
        text, target = self.corpus[idx], self.labels[idx]
        target = self.label_encoder.transform([target])[0]
        for t in self.transforms:
            text = t(text)
        return text, target
