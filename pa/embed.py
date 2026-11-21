"""Tiny lexical embedding: hashed words + char trigrams, L2-normalised.
NOT a neural/semantic model: it matches shared words and spellings only."""
import math
import re
import zlib
from array import array

from . import config

STOP = set("ke ka ki ko mein me par pe se hai hain tha thi the kya maine mujhe mera meri aur "
           "a an of in on for to is was what did i about".split())


def tokens(text):
    return [w for w in re.findall(r"\w+", text.lower()) if w not in STOP]


def embed(text):
    v = [0.0] * config.EMBED_DIM
    for w in tokens(text):
        feats = [(w, 1.0)] + [("#" + w[i:i + 3], 0.5) for i in range(max(1, len(w) - 2))]
        for f, wt in feats:
            h = zlib.crc32(f.encode())
            v[h % config.EMBED_DIM] += wt if (h >> 16) & 1 else -wt
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def pack(v):
    return array("f", v).tobytes()


def unpack(b):
    a = array("f")
    a.frombytes(b)
    return list(a)


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))
