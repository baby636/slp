import itertools
from collections import Counter
import errno
import os

import numpy as np
from loguru import logger
from enum import Enum

from tqdm import tqdm
from typing import cast, Any, Dict, Optional, List, Union, Iterator, Tuple

from slp.data.transforms import SpacyTokenizer, HuggingFaceTokenizer, ToTokenIds
import slp.util.system as system
import slp.util.types as types
from slp.config.nlp import SPECIAL_TOKENS


def create_vocab(
    corpus: Union[List[str], List[List[str]]],
    vocab_size: int = -1,
    special_tokens: Optional[SPECIAL_TOKENS] = None,
) -> Dict[str, int]:
    """Create the vocabulary based on tokenized input corpus

    * Injects special tokens in the vocabulary
    * Calculates the occurence count for each token
    * Limits vocabulary to vocab_size most common tokens

    Args:
        corpus (Union[List[str], List[List[str]]]): The tokenized corpus as single stream or a list of tokenized sentences
        vocab_size (int, optional): [description]. Limit vocabulary to vocab_size most common tokens.
            Defaults to -1 which keeps all tokens.
        special_tokens Optional[SPECIAL_TOKENS]: Special tokens to include in the vocabulary. Defaults to None.

    Returns:
        Dict[str, int]: Dictionary of all accepted tokens and their corresponding occurence counts

    Examples:
        >>> create_vocab(["in", "a", "galaxy", "far", "far", "away"])
        {'far': 2, 'away': 1, 'galaxy': 1, 'a': 1, 'in': 1}
        >>> create_vocab(["in", "a", "galaxy", "far", "far", "away"], vocab_size=3)
        {'far': 2, 'a': 1, 'in': 1}
        >>> create_vocab(["in", "a", "galaxy", "far", "far", "away"], vocab_size=3, special_tokens=slp.config.nlp.SPECIAL_TOKENS)
        {'[PAD]': 0, '[MASK]': 0, '[UNK]': 0, '[BOS]': 0, '[EOS]': 0, '[CLS]': 0, '[SEP]': 0, 'far': 2, 'a': 1, 'in': 1}
    """
    if isinstance(corpus[0], list):
        corpus = list(itertools.chain.from_iterable(corpus))
    freq = Counter(corpus)
    if special_tokens is None:
        extra_tokens = []
    else:
        extra_tokens = special_tokens.to_list()
    if vocab_size < 0:
        vocab_size = len(freq)
    take = min(vocab_size, len(freq))
    logger.info(f"Keeping {vocab_size} most common tokens out of {len(freq)}")

    def take0(x: Tuple[Any, Any]) -> Any:
        return x[0]

    common_words = list(map(take0, freq.most_common(take)))
    common_words = list(set(common_words) - set(extra_tokens))
    words = extra_tokens + common_words
    if len(words) > vocab_size:
        words = words[: vocab_size + len(extra_tokens)]

    def token_freq(t):
        return 0 if t in extra_tokens else freq[t]

    vocab = dict(zip(words, map(token_freq, words)))
    logger.info(f"Vocabulary created with {len(vocab)} tokens.")
    logger.info(f"The 10 most common tokens are:\n{freq.most_common(10)}")

    return vocab


class EmbeddingsLoader(object):
    def __init__(
        self,
        embeddings_file: str,
        dim: int,
        vocab: Optional[Dict[str, int]] = None,
        extra_tokens: Optional[SPECIAL_TOKENS] = None,
    ) -> None:
        """Load word embeddings in text format

        Args:
            embeddings_file (str): File where embeddings are stored (e.g. glove.6B.50d.txt)
            dim (int): Dimensionality of embeddings
            vocab (Optional[Dict[str, int]]): Load only embeddings in vocab. Defaults to None.
            extra_tokens (Optional[slp.config.nlp.SPECIAL_TOKENS]): Create random embeddings for these special tokens.
                Defaults to None.
        """
        self.embeddings_file = embeddings_file
        self.vocab = vocab
        self.cache_ = self._get_cache_name()
        self.dim_ = dim
        self.extra_tokens = extra_tokens

    def __repr__(self):
        return f"{self.__class__.__name__}({self.embeddings_file}, {self.dim_})"

    def in_accepted_vocab(self, word: str) -> bool:
        """Check if word exists in given vocabulary

        Args:
            word (str): word from embeddings file

        Returns:
            bool: Word exists
        """
        if self.vocab is None:
            return True
        else:
            return word in self.vocab

    def _get_cache_name(self) -> str:
        """Create a cache file name to avoid reloading the embeddings

        Cache name is something like glove.6B.50d.1000.p,
        where 1000 is the size of the vocab provided in __init__

        Returns:
            str: Cache file name
        """
        head, tail = os.path.split(self.embeddings_file)
        filename, ext = os.path.splitext(tail)
        if self.vocab is not None:
            cache_name = os.path.join(head, f"{filename}.{len(self.vocab)}.p")
        else:
            cache_name = os.path.join(head, f"{filename}.p")
        logger.info(f"Cache: {cache_name}")
        return cache_name

    def _dump_cache(self, data: types.Embeddings) -> None:
        """Save loaded embeddings to cache as a pickle

        Saves a tuple of (word2idx, idx2word, embeddings)

        Args:
            data (types.Embeddings): (word2idx, idx2word, embeddings) tuple
        """
        system.pickle_dump(data, self.cache_)

    def _load_cache(self) -> types.Embeddings:
        """Load Embeddings from cache

        Returns:
            types.Embeddings: (word2idx, idx2word, embeddings) tuple
        """
        return cast(types.Embeddings, system.pickle_load(self.cache_))

    def augment_embeddings(
        self,
        word2idx: Dict[str, int],
        idx2word: Dict[int, str],
        embeddings: List[np.ndarray],
        token: str,
        emb: Optional[np.ndarray] = None,
    ) -> Tuple[Dict[str, int], Dict[int, str], List[np.ndarray]]:
        """Create a random embedding for a special token and append it to the embeddings array

        Args:
            word2idx (Dict[str, int]): Current word2idx map
            idx2word (Dict[int, str]): Current idx2word map
            embeddings (List[np.ndarray]): Embeddings array as list of embeddings
            token (str): The special token (e.g. [PAD])
            emb (Optional[np.ndarray]): Optional value for the embedding to be appended.
                Defaults to None, where a random embedding is created.

        Returns:
            Tuple[Dict[str, int], Dict[int, str], List[np.ndarray]]: (word2idx, idx2word, embeddings) tuple
        """
        word2idx[token] = len(embeddings)
        idx2word[len(embeddings)] = token
        if emb is None:
            emb = np.random.uniform(low=-0.05, high=0.05, size=self.dim_)
        embeddings.append(emb)
        return word2idx, idx2word, embeddings

    @system.timethis(method=True)
    def load(self) -> types.Embeddings:
        """Read the word vectors from a text file

        * Read embeddings
        * Filter with given vocabulary
        * Augment with special tokens

        Returns:
            types.Embeddings: (word2idx, idx2word, embeddings) tuple
        """
        # in order to avoid this time consuming operation, cache the results
        try:
            cache = self._load_cache()
            logger.info("Loaded word embeddings from cache.")
            return cache
        except OSError:
            logger.warning(f"Didn't find embeddings cache file {self.embeddings_file}")
            logger.warning("Loading embeddings from file.")

        # create the necessary dictionaries and the word embeddings matrix
        if not os.path.exists(self.embeddings_file):
            logger.critical(f"{self.embeddings_file} not found!")
            raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), self.embeddings_file)

        logger.info(f"Indexing file {self.embeddings_file} ...")

        # create the 2D array, which will be used for initializing
        # the Embedding layer of a NN.
        # We reserve the first row (idx=0), as the word embedding,
        # which will be used for zero padding (word with id = 0).
        if self.extra_tokens is not None:
            word2idx, idx2word, embeddings = self.augment_embeddings(
                {},
                {},
                [],
                self.extra_tokens.PAD.value,  # type: ignore
                emb=np.zeros(self.dim_),
            )

            for token in self.extra_tokens:  # type: ignore
                logger.debug(f"Adding token {token.value} to embeddings matrix")
                if token == self.extra_tokens.PAD:
                    continue
                word2idx, idx2word, embeddings = self.augment_embeddings(
                    word2idx, idx2word, embeddings, token.value
                )
        else:
            word2idx, idx2word, embeddings = self.augment_embeddings(
                {}, {}, [], "[PAD]", emb=np.zeros(self.dim_)
            )
        # read file, line by line
        with open(self.embeddings_file, "r") as f:
            num_lines = sum(1 for line in f)

        with open(self.embeddings_file, "r") as f:
            index = len(embeddings)

            for line in tqdm(
                f, total=num_lines, desc="Loading word embeddings...", leave=False
            ):
                # skip the first row if it is a header
                if len(line.split()) < self.dim_:
                    continue

                values = line.rstrip().split(" ")
                word = values[0]

                if word in word2idx:
                    continue

                if not self.in_accepted_vocab(word):
                    continue

                vector = np.asarray(values[1:], dtype=np.float32)
                idx2word[index] = word
                word2idx[word] = index
                embeddings.append(vector)
                index += 1

        logger.info(f"Loaded {len(embeddings)} word vectors.")
        embeddings_out = np.array(embeddings, dtype="float32")

        # write the data to a cache file
        self._dump_cache((word2idx, idx2word, embeddings_out))
        return word2idx, idx2word, embeddings_out


class WordCorpus(object):
    def __init__(
        self,
        corpus: List[List[str]],
        limit_vocab_size: int = 30000,
        word2idx: Optional[Dict[str, int]] = None,
        idx2word: Optional[Dict[int, str]] = None,
        embeddings: Optional[np.ndarray] = None,
        embeddings_file: Optional[str] = None,
        embeddings_dim: int = 300,
        lower: bool = True,
        special_tokens: Optional[SPECIAL_TOKENS] = SPECIAL_TOKENS,  # type: ignore
        prepend_bos: bool = False,
        append_eos: bool = False,
        lang: str = "en_core_web_md",
        max_len: int = -1,
        **kwargs,
    ):
        # FIXME: Extract super class to avoid repetition
        self.corpus_ = corpus
        self.max_len = max_len
        self.tokenizer = SpacyTokenizer(
            lower=lower,
            prepend_bos=prepend_bos,
            append_eos=append_eos,
            specials=special_tokens,
            lang=lang,
        )

        logger.info(f"Tokenizing corpus using spacy {lang}")

        self.tokenized_corpus_ = [
            self.tokenizer(s)
            for s in tqdm(self.corpus_, desc="Tokenizing corpus...", leave=False)
        ]

        self.vocab_ = create_vocab(
            self.tokenized_corpus_,
            vocab_size=limit_vocab_size if word2idx is None else -1,
            special_tokens=special_tokens,
        )

        self.word2idx_, self.idx2word_, self.embeddings_ = None, None, None
        self.corpus_indices_ = self.tokenized_corpus_

        if word2idx is not None:
            logger.info("Word2idx was already provided. Going to used it.")

        if embeddings_file is not None and word2idx is None:
            logger.info(
                f"Going to load {len(self.vocab_)} embeddings from {embeddings_file}"
            )
            loader = EmbeddingsLoader(
                embeddings_file,
                embeddings_dim,
                vocab=self.vocab_,
                extra_tokens=special_tokens,
            )
            word2idx, idx2word, embeddings = loader.load()

        if embeddings is not None:
            self.embeddings_ = embeddings

        if idx2word is not None:
            self.idx2word_ = idx2word

        if word2idx is not None:
            self.word2idx_ = word2idx

            logger.info("Converting tokens to ids using word2idx.")
            self.to_token_ids = ToTokenIds(self.word2idx_, specials=SPECIAL_TOKENS)
            self.corpus_indices_ = [
                self.to_token_ids(s)
                for s in tqdm(
                    self.tokenized_corpus_,
                    desc="Converting tokens to token ids...",
                    leave=False,
                )
            ]

            logger.info("Filtering corpus vocabulary.")

            updated_vocab = {}
            for k, v in self.vocab_.items():
                if k in self.word2idx_:
                    updated_vocab[k] = v

            logger.info(
                f"Out of {len(self.vocab_)} tokens {len(self.vocab_) - len(updated_vocab)} were not found in the pretrained embeddings."
            )

            self.vocab_ = updated_vocab

    @property
    def vocab_size(cls):
        return (
            cls.embeddings.shape[0] if cls.embeddings is not None else len(cls.vocab_)
        )

    @property
    def frequencies(cls):
        return cls.vocab_

    @property
    def vocab(cls):
        return set(cls.vocab_.keys())

    @property
    def embeddings(cls):
        return cls.embeddings_

    @property
    def word2idx(cls):
        return cls.word2idx_

    @property
    def idx2word(cls):
        return cls.idx2word_

    @property
    def tokenized(cls):
        return self.tokenized_corpus_

    @property
    def indices(cls):
        return self.corpus_indices_

    @property
    def raw(cls):
        return self.corpus_

    def __len__(self):
        return len(self.corpus_indices_)

    def __getitem__(self, idx):
        indices = self.corpus_indices_[idx]
        return (
            self.corpus_indices_[idx]
            if self.max_len <= 0
            else self.corpus_indices_[idx][: self.max_len]
        )


class HfCorpus(object):
    def __init__(
        self,
        corpus,
        lower=True,
        tokenizer_model="bert-base-uncased",
        add_special_tokens=True,
        special_tokens=SPECIAL_TOKENS,
        max_len=-1,
        **kwargs,
    ):
        self.corpus_ = corpus
        self.max_len = max_len

        logger.info(
            f"Tokenizing corpus using hugging face tokenizer from {tokenizer_model}"
        )

        self.tokenizer = HuggingFaceTokenizer(
            lower=lower, model=tokenizer_model, add_special_tokens=add_special_tokens
        )

        self.corpus_indices_ = [
            self.tokenizer(s)
            for s in tqdm(
                self.corpus_, desc="Converting tokens to indices...", leave=False
            )
        ]

        self.tokenized_corpus_ = [
            self.tokenizer.detokenize(s)
            for s in tqdm(
                self.corpus_indices_,
                desc="Mapping indices to tokens...",
                leave=False,
            )
        ]

        self.vocab_ = create_vocab(
            self.tokenized_corpus_,
            vocab_size=-1,
            special_tokens=special_tokens,
        )

    @property
    def vocab_size(cls):
        return cls.tokenizer.vocab_size

    @property
    def frequencies(cls):
        return cls.vocab_

    @property
    def embeddings(cls):
        return None

    @property
    def word2idx(cls):
        return None

    @property
    def idx2word(cls):
        return None

    @property
    def tokenized(cls):
        return self.tokenized_corpus_

    @property
    def indices(cls):
        return self.corpus_indices_

    @property
    def raw(cls):
        return self.corpus_

    def __len__(self):
        return len(self.corpus_indices_)

    def __getitem__(self, idx):
        return (
            self.corpus_indices_[idx]
            if self.max_len <= 0
            else self.corpus_indices_[idx][: self.max_len]
        )


class TokenizedCorpus(object):
    def __init__(
        self,
        corpus,
        word2idx=None,
        special_tokens=SPECIAL_TOKENS,
        max_len=-1,
        **kwargs,
    ):
        self.corpus_ = corpus
        self.tokenized_corpus_ = corpus
        self.max_len = max_len

        self.vocab_ = create_vocab(
            self.tokenized_corpus_,
            vocab_size=-1,
            special_tokens=special_tokens,
        )

        if word2idx is not None:
            logger.info("Converting tokens to ids using word2idx.")
            self.word2idx_ = word2idx
        else:
            logger.info(
                "No word2idx provided. Will convert tokens to ids using an iterative counter."
            )
            self.word2idx_ = dict(zip(self.vocab_.keys(), itertools.count()))

        self.idx2word_ = {v: k for k, v in self.word2idx_.items()}

        self.to_token_ids = ToTokenIds(self.word2idx_, specials=SPECIAL_TOKENS)
        if isinstance(self.tokenized_corpus_[0], list):
            self.corpus_indices_ = [
                self.to_token_ids(s)
                for s in tqdm(
                    self.tokenized_corpus_,
                    desc="Converting tokens to token ids...",
                    leave=False,
                )
            ]
        else:
            self.corpus_indices_ = self.to_token_ids(self.tokenized_corpus_)

    @property
    def vocab_size(cls):
        return len(cls.vocab_)

    @property
    def frequencies(cls):
        return cls.vocab_

    @property
    def vocab(cls):
        return set(cls.vocab_.keys())

    @property
    def embeddings(cls):
        return None

    @property
    def word2idx(cls):
        return cls.word2idx_

    @property
    def idx2word(cls):
        return cls.idx2word_

    @property
    def tokenized(cls):
        return self.tokenized_corpus_

    @property
    def indices(cls):
        return self.corpus_indices_

    @property
    def raw(cls):
        return self.corpus_

    def __len__(self):
        return len(self.corpus_indices_)

    def __getitem__(self, idx):
        return (
            self.corpus_indices_[idx]
            if self.max_len <= 0
            else self.corpus_indices_[idx][: self.max_len]
        )


if __name__ == "__main__":
    corpus = [
        [
            "the big",
            "brown fox",
            "jumps over",
            "the lazy dog",
            "supercalifragilisticexpialidocious",
        ]
    ]

    word_corpus = WordCorpus(
        corpus,
        embeddings_file="./cache/glove.6B.50d.txt",
        embeddings_dim=50,
        lower=True,
        prepend_bos=True,
        append_eos=True,
    )

    hugging_face_corpus = HfCorpus(corpus)
