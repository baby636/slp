import argparse
import os
import sys
from pprint import pprint

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from ignite.metrics import Accuracy, Fbeta, Loss, MeanAbsoluteError
from torch.utils.data import DataLoader

from slp.config.nlp import SPECIAL_TOKENS
from slp.data.collators import MOSICollator
from slp.data.mosi import MOSI
from slp.data.transforms import ToTensor, ToTokenIds
from slp.mm.load import mosi
# from slp.data.transforms import InstanceNorm, ToTokenIds, ToTensor, FilterCovarep
from slp.modules.multimodal import AudioTextClassifier
from slp.modules.rnn import WordRNN
from slp.trainer import MOSITrainer
from slp.ui.config import load_config
from slp.util import log
from slp.util.embeddings import EmbeddingsLoader
from slp.util.system import safe_mkdirs

class BCE(nn.Module):
    def __init__(self):
        super(BCE, self).__init__()

    def forward(self, out, tgt):
        tgt = tgt.view(-1, 1).float()

        return F.binary_cross_entropy_with_logits(out, tgt)


def get_parser():
    parser = argparse.ArgumentParser(description="CLI parser for experiment")

    parser.add_argument(
        "--binary",
        dest="binary",
        default=False,
        action="store_true",
        help="Use binary task",
    )

    parser.add_argument(
        "--remove-pauses",
        dest="remove_pauses",
        default=False,
        action="store_true",
        help="Remove speaker pauses",
    )

    parser.add_argument(
        "--modalities",
        dest="modalities",
        default=None,
        nargs="+",
        help="Modalities to use",
    )

    parser.add_argument(
        "--audio-dim",
        dest="audio.dim",
        default=None,
        type=int,
        help="Audio features dimension",
    )

    parser.add_argument(
        "--audio-instance-norm",
        dest="audio.instance_norm",
        action="store_true",
        help="Audio instance normalization",
    )

    parser.add_argument(
        "--audio-batchnorm",
        dest="audio.batchnorm",
        action="store_true",
        help="Audio batch normalization",
    )

    parser.add_argument(
        "--audio-layers",
        dest="audio.layers",
        default=None,
        type=int,
        help="Num layers for audio encoder",
    )

    parser.add_argument(
        "--text-layers",
        dest="text.layers",
        default=None,
        type=int,
        help="Num layers for text encoder",
    )

    parser.add_argument(
        "--audio-hidden-size",
        dest="audio.hidden_size",
        default=None,
        type=int,
        help="Hidden size for RNNs",
    )

    parser.add_argument(
        "--text-hidden-size",
        dest="text.hidden_size",
        default=None,
        type=int,
        help="Hidden size for RNNs",
    )

    parser.add_argument(
        "--dropout",
        dest="common.dropout",
        default=None,
        type=float,
        help="Dropout probabiity",
    )

    parser.add_argument(
        "--proj-size",
        dest="fuse.projection_size",
        default=None,
        type=int,
        help="Modality projection size",
    )

    parser.add_argument(
        "--bidirectional",
        dest="common.bidirectional",
        action="store_true",
        help="Use BiRNNs",
    )

    parser.add_argument(
        "--rnn-type", dest="common.rnn_type", default=None, type=str, help="lstm or gru"
    )

    parser.add_argument(
        "--text-attention",
        dest="text.attention",
        action="store_true",
        help="Use RNN with attention",
    )

    parser.add_argument(
        "--audio-attention",
        dest="audio.attention",
        action="store_true",
        help="Use RNN with attention",
    )

    parser.add_argument(
        "--fuse", dest="fuse.method", default=None, type=str, help="cat or add"
    )

    parser.add_argument(
        "--modality-weights",
        dest="fuse.modality_weights",
        action="store_true",
        help="Use modality weights during fusion",
    )

    parser.add_argument(
        "--feedback",
        dest="feedback",
        action="store_true",
        help="Use feedback fusion",
    )

    parser.add_argument(
        "--result-dir",
        dest="results_dir",
        help="Results directory",
    )

    return parser


C = load_config(parser=get_parser())
C["modalities"] = set(C["modalities"])

collate_fn = MOSICollator(
    device="cpu", binary=False, modalities=["text", "audio"], max_length=-1
)


if __name__ == "__main__":
    log.info("Running with configuration")
    pprint(C)
    train, dev, test, vocab = mosi(
        C["data_dir"],
        modalities=C["modalities"],
        remove_pauses=False,  # C['remove_pauses'],
        max_length=-1,
        pad_front=True,
        pad_back=False,
        cache=os.path.join(C["cache_dir"], "mosi.p"),
    )

    if "glove" in C["modalities"]:
        for d in train:
            d["text"] = d["glove"]

        for d in dev:
            d["text"] = d["glove"]

        for d in test:
            d["text"] = d["glove"]

    embeddings = None

    if "glove" not in C["modalities"]:
        loader = EmbeddingsLoader(
            C["embeddings"]["path"],
            C["embeddings"]["dim"],
            extra_tokens=SPECIAL_TOKENS,
            vocab=vocab,
        )
        word2idx, idx2word, embeddings = loader.load()

        to_token_ids = ToTokenIds(word2idx)
    # covarep_filter = FilterCovarep()
    to_tensor = ToTensor(device="cpu")
    to_tensor_float = ToTensor(device="cpu", dtype=torch.float)
    # instance_norm = InstanceNorm()

    def create_dataloader(data):
        d = (
            MOSI(data, modalities=C["modalities"])
            # .map(covarep_filter, 'audio', lazy=True)
            # .map(instance_norm, 'visual', lazy=True)
        )
        d.map(to_tensor_float, "visual", lazy=True)

        if "glove" not in C["modalities"]:
            d.map(to_tensor, "text", lazy=True)
            d.map(to_token_ids, "text", lazy=True)

        if "glove" in C["modalities"]:
            d.map(to_tensor_float, "text", lazy=True)

        # if C["audio"]["instance_norm"]:
        # d = d.map(instance_norm, "audio", lazy=True)
        d = d.map(to_tensor_float, "audio", lazy=True)
        d.apply_transforms()
        dataloader = DataLoader(
            d,
            batch_size=C["dataloaders"]["batch_size"],
            num_workers=0,  # C['dataloaders']['num_workers'],
            pin_memory=C["dataloaders"]["batch_size"],
            shuffle=True,
            collate_fn=collate_fn,
        )

        return dataloader

    text_mode = "glove" if "glove" in C["modalities"] else "raw"
    train_loader, dev_loader, test_loader = map(create_dataloader, [train, dev, test])
    x = next(iter(train_loader))

    print("Running with feedback = {}".format(C["feedback"]))

    model = AudioTextClassifier(
        embeddings=embeddings,
        audio_cfg=C["audio"]["model"],
        text_cfg=C["text"]["model"],
        fuse_cfg=C["fuse"],
        device=C["device"],
        modalities=C["modalities"],
        text_mode="glove",
        audio_mode="sequential",
        num_classes=1,
        feedback=C["feedback"],
    )
    model = model.to(C["device"])
    optimizer = getattr(torch.optim, C["optimizer"]["name"])(
        [p for p in model.parameters() if p.requires_grad],
        lr=C["optimizer"]["learning_rate"],
    )

    if C["binary"]:
        criterion = BCE()

        def thresholded_output_transform(output):
            y_pred, y = output
            y_pred = torch.sigmoid(y_pred)
            y_pred = torch.round(y_pred)

            return y_pred, y

        metrics = {
            "bin_accuracy": Accuracy(thresholded_output_transform),
            "loss": Loss(criterion),
        }
        # score_fn = lambda engine: engine.state.metrics["bin_accuracy"]
    else:
        criterion = nn.L1Loss()

        def bin_acc_transform(output):
            y_pred, y = output
            yp, yt = (y_pred > 0).long(), (y > 0).long()

            return yp, yt

        def mult_acc_transform(output):
            y_pred, y = output
            yp = torch.clamp(torch.round(y_pred) + 3, 0, 6).view(-1).long()
            yt = torch.round(y).view(-1).long() + 3
            yp = F.one_hot(yp, 7)

            return yp, yt

        metrics = {
            #"bin_accuracy": Accuracy(output_transform=bin_acc_transform),
            #"mae": MeanAbsoluteError(),
            #"mult_accuracy": Accuracy(output_transform=mult_acc_transform),
            #"f1": Fbeta(1, output_transform=bin_acc_transform),
            "loss": Loss(criterion),
        }
        # score_fn = lambda engine: engine.state.metrics["f1"]

    if C["overfit_batch"] or C["overfit_batch"] or C["train"]:
        trainer = MOSITrainer(
            model,
            optimizer,
            # score_fn=score_fn,
            experiment_name=C["experiment"]["name"],
            checkpoint_dir=C["trainer"]["checkpoint_dir"],
            metrics=metrics,
            non_blocking=C["trainer"]["non_blocking"],
            patience=C["trainer"]["patience"],
            validate_every=C["trainer"]["validate_every"],
            retain_graph=C["trainer"]["retain_graph"],
            loss_fn=criterion,
            device=C["device"],
        )

    if C["debug"]:
        if C["overfit_batch"]:
            trainer.overfit_single_batch(train_loader)
        trainer.fit_debug(train_loader, dev_loader)
        sys.exit(0)

    if C["train"]:
        trainer.fit(train_loader, dev_loader, epochs=C["trainer"]["max_epochs"])

    if C["test"]:
        try:
            del trainer
        except:
            pass
        trainer = MOSITrainer(
            model,
            optimizer,
            experiment_name=C["experiment"]["name"],
            checkpoint_dir=C["trainer"]["checkpoint_dir"],
            metrics=metrics,
            model_checkpoint=C["trainer"]["load_model"],
            non_blocking=C["trainer"]["non_blocking"],
            patience=C["trainer"]["patience"],
            validate_every=C["trainer"]["validate_every"],
            retain_graph=C["trainer"]["retain_graph"],
            loss_fn=criterion,
            device=C["device"],
        )

        predictions, targets = trainer.predict(test_loader)

        pred = torch.cat(predictions)
        y_test = torch.cat(targets)

        from slp.util.mosei_metrics import eval_mosei_senti, print_metrics, save_metrics

        metrics = eval_mosei_senti(pred, y_test, True)
        print_metrics(metrics)

        import uuid

        results_dir = C["results_dir"]
        safe_mkdirs(results_dir)
        results_file = os.path.join(results_dir, uuid.uuid1().hex)

        save_metrics(metrics, results_file)