from typing import Any, Callable, Dict, List, Optional, Set, Union

import numpy as np
from toolz import compose_left, pipe
from torch.utils.data import Dataset
from tqdm import tqdm


class MMDataset(Dataset):
    def __init__(
        self,
        data: List[Dict[str, Any]],
        modalities: Union[List[str], Set[str]] = {"text", "audio", "visual"},
    ):
        self.data = data
        self.modalities = modalities

        self.transforms: Dict[str, List[Callable]] = {m: [] for m in self.modalities}
        self.transforms["label"] = []

    def map(self, fn: Callable, modality: str, lazy: bool = True) -> MMDataset:
        if modality not in self.modalities:
            return self
        self.transforms[modality].append(fn)

        if not lazy:
            self.apply_transforms()

        return self

    def apply_transforms(self) -> MMDataset:
        for m in self.modalities:
            if len(self.transforms[m]) == 0:
                continue
            fn = compose_left(*self.transforms[m])
            # In place transformation to save some mem.

            for i in tqdm(
                range(len(self.data)),
                desc=f"Applying transforms for {m}",
                total=len(self.data),
            ):
                self.data[i][m] = fn(self.data[i][m])
        self.transforms = {m: [] for m in self.modalities}

        return self

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        dat = self.data[idx]

        for m in self.modalities:
            if len(self.transforms[m]) == 0:
                continue
            dat[m] = pipe(dat[m], *self.transforms[m])

        return dat


def binarize(x):
    return 0.5 * (1.0 + np.sign(x)).astype(int)


class MOSI(MMDataset):
    def __init__(
        self,
        data: List[Dict[str, Any]],
        modalities: Union[List[str], Set[str]] = {"text", "audio", "visual"},
        binary: bool = False,
    ):
        super(MOSI, self).__init__(data, modalities)

        def label_selector(l):
            return l.item()

        self.transforms["label"].append(label_selector)

        if binary:
            self.transforms["label"].append(binarize)


class MOSEI(MMDataset):
    def __init__(
        self,
        data: List[Dict[str, Any]],
        modalities: Union[List[str], Set[str]] = {"text", "audio", "visual"},
        label_selector: Optional[Callable] = None,
    ):
        super(MOSEI, self).__init__(data, modalities)

        def default_label_selector(l):
            return l[0]

        if label_selector is None:
            label_selector = default_label_selector

        self.transforms["label"].append(label_selector)
