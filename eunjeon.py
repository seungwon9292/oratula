"""Python 3.12 compatible adapter used by g2pK on Windows."""
from kiwipiepy import Kiwi


class Mecab:
    def __init__(self):
        self._kiwi = Kiwi()

    def pos(self, phrase, flatten=True, join=False):
        return [(token.form, token.tag) for token in self._kiwi.tokenize(phrase)]
