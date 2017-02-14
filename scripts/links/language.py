#!/usr/bin/env python
from __future__ import print_function
import argparse

import chainer
import chainer.functions as F
import chainer.links as L
from chainer import training
from chainer.training import extensions
from chainer import reporter
from chainer import cuda

import numpy as np


def choice_by_gumbel_max_trick(probs):
    xp = cuda.get_array_module(probs.data)
    noise = xp.random.gumbel(loc=0, scale=1, size=probs.shape)
    sampled_ids = F.argmax(probs + noise, axis=1)
    return sampled_ids


class NaiveLanguage(chainer.Chain):

    def __init__(self, n_units, n_vocab, n_turn,
                 share=False, listener=False, speaker=False):
        if share:
            super(NaiveLanguage, self).__init__(
                definition=L.EmbedID(n_vocab, n_units),
                interpreter=L.StatefulGRU(n_units, n_units),
                decoder=L.StatefulGRU(n_units, n_units),
            )
        elif listener:
            super(NaiveLanguage, self).__init__(
                definition=L.EmbedID(n_vocab, n_units),
                interpreter=L.StatefulGRU(n_units, n_units),
            )
        elif speaker:
            super(NaiveLanguage, self).__init__(
                definition=L.EmbedID(n_vocab, n_units),
                decoder=L.StatefulGRU(n_units, n_units),
            )
        else:
            print('choose language type. [share, listener, speaker]')
            exit()

        self.n_vocab = n_vocab
        self.n_units = n_units

        self.add_param('eos', (n_units,), dtype='f')
        self.eos.data[:] = 0
        self.add_param('bos', (n_units,), dtype='f')
        self.bos.data[:] = 0

    def decode_word(self, x, train=True):
        match_score = F.linear(x, self.definition.W)
        probability = F.softmax(match_score)

        if train:
            sampled_ids = choice_by_gumbel_max_trick(probability)
        else:
            sampled_ids = F.argmax(probability, axis=1)

        sampled_probability = F.select_item(probability, sampled_ids)
        return sampled_ids, sampled_probability, probability

    def interpret_word(self, x):
        return self.definition(x)

    def interpret_sentence(self, x_seq, train=True):
        self.interpreter.reset_state()

        for message_word in x_seq:
            message_meaning = self.interpreter(
                self.interpret_word(message_word))

        self.interpreter.reset_state()
        return message_meaning

    def decode_thought(self, thought, n_word, train=True):
        sampled_word_idx_seq = []
        total_log_probability = 0.
        p_dists = []
        if n_word == 1:
            sampled_word_idx, probability, p_dist = self.decode_word(
                thought, train=train)
            sampled_word_idx_seq.append(sampled_word_idx)
            total_log_probability += F.log(probability)
            p_dists.append(p_dist)
        else:
            self.decoder.reset_state()
            self.decoder.h = thought
            x_input = F.broadcast_to(
                self.bos, (thought.data.shape[0], len(self.bos.data)))

            # TODO: beam-search
            for i in range(n_word):
                h = self.decoder(x_input)
                sampled_word_idx, probability, p_dist = self.decode_word(
                    h, train=train)
                sampled_word_idx_seq.append(sampled_word_idx)
                total_log_probability += F.log(probability)
                p_dists.append(p_dist)
                x_input = self.interpret_word(sampled_word_idx)
            self.decoder.reset_state()
        return sampled_word_idx_seq, total_log_probability, p_dists
