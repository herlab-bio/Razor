#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 15 12:51:51 2020

@author: bikash, CS Lim
"""

import sys, argparse, re, multiprocessing
from pathlib import Path

import numpy as np
import pandas
from pandarallel import pandarallel
import tqdm

from libs import detector

tqdm.tqdm.pandas()


def check_file(file):
    fasta = Path(file)
    if fasta.is_file():
        return file
    else:
        raise argparse.ArgumentTypeError('Fasta file not found.')


def check_seq(seq, max_scan=80):
    '''Check for standard amino acid code up to max_scan + 15
    '''
    seq = seq.upper()[: max_scan + 15].replace("U", "C")
    valid_aa = re.compile("^[RKNDQEHPYWSTGAMCFLVI]*$")
    match = re.match(valid_aa, seq)

    if match:
        return True
    else:
        return False


def fasta_reader(file, max_scan):
    '''Converts .fasta to a pandas dataframe with accession as index
    and sequence in a column 'sequence'
    '''
    try:

        fasta_df = pandas.read_csv(file, sep='>', lineterminator='>', header=None)
        fasta_df[['Accession', 'Sequence']] = fasta_df[0].str.split('\n', n=1, expand=True)
        fasta_df['Accession'] = fasta_df['Accession']
        fasta_df['Sequence'] = fasta_df['Sequence'].replace('\n', '', regex=True).\
            astype(str).str.upper().replace('U', 'C').str[:max_scan + 15]
        total_seq = fasta_df.shape[0]
        fasta_df.drop(0, axis=1, inplace=True)
        # fasta_df = fasta_df[~fasta_df['Sequence'].str.contains('B|J|O|U|X|Z')].copy()
        fasta_df['check'] = fasta_df.Sequence.apply(lambda x: check_seq(x))
        fasta_df = fasta_df[fasta_df.check].drop('check', axis=1)
        fasta_df = fasta_df[(fasta_df.Sequence != '') & (fasta_df.Sequence != 'NONE')]
        final_df = fasta_df.dropna()
        remained_seq = final_df.shape[0]
        if total_seq != remained_seq:
            print("{} sequences were removed due to inconsistencies in"
                  " the provided file.".format(total_seq - remained_seq))
        return final_df
    except Exception:
        raise argparse.ArgumentTypeError('Something is wrong with the fasta file.')


def check_max_scan(m):
    try:
        m = int(m)
    except Exception:
        raise argparse.ArgumentTypeError('Max scan should be an integer.')
    if m < 16:
        raise argparse.ArgumentTypeError('Max scan should be greater than 16.')
    else:
        return m


def razor_predict(seq, max_scan):
    '''
    Prediction
    '''
    newObj = detector.RAZOR(seq=seq, max_scan=max_scan)
    _ = newObj.predict()
    try:
        _ = newObj.fungi()
        _ = newObj.toxin()
    except TypeError:
        pass
    try:
        cleav = newObj.final_cleavage.tolist()[0]
    except Exception:
        cleav = 0

    y_score = np.around(newObj.y_scores, 2).tolist()
    predictions = newObj.preds.tolist()
    max_c_scores = newObj.c_scores.tolist()
    possible_cleavage = newObj.cleavage_sites.tolist()
    cleavage = cleav
    final_score_sp = np.around(newObj.final_score_sp, 2)
    fungi_scores = newObj.fungi_scores.tolist()
    fungi_preds = newObj.fungi_preds.tolist()
    final_score_fungi = newObj.final_score_fungi
    toxin_scores = newObj.toxin_scores.tolist()
    toxin_preds = newObj.toxin_preds.tolist()
    final_score_toxin = newObj.final_score_toxin
    return y_score, predictions, max_c_scores, possible_cleavage, cleavage, final_score_sp, fungi_scores, fungi_preds, final_score_fungi, toxin_scores, toxin_preds, final_score_toxin


def get_args():
    '''arguments.
    '''
    parser = argparse.ArgumentParser(prog='Razor',
                                     description='A tool to detect signal peptide',
                                     epilog='(c) Authors')
    parser.add_argument('-p', '--path',
                        help='Path to fasta file',
                        required='True')
    parser.add_argument('-o', '--output',
                        help='Output file name.',
                        default='result')
    parser.add_argument('-m', '--max_scan',
                        help='Check for cleavage site upto this residue. Default: '
                        '80',
                        type=check_max_scan,
                        default=80)
    parser.add_argument('-n', '--ncores',
                        help='Number of cores to use. Default: '
                        '1/4 of total cores.',
                        type=int,
                        default=multiprocessing.cpu_count() // 2)
    parser.add_argument('-q', '--quiet',
                        help='Suppress warnings.',
                        action='store_true')

    return parser.parse_args()


def main(path, output_path, max_scan=80, ncores=1):

    df = fasta_reader(path, max_scan=max_scan)

    if ncores == 1:
        df['Analysis_'] = df['Sequence'].progress_apply(lambda x: razor_predict(x, max_scan))
    else:
        df['Analysis_'] = df['Sequence'].parallel_apply(lambda x: razor_predict(x, max_scan))

    columns = ['Y_score', 'SP_Prediction', 'Max_C',
               'Probable Cleavage after', 'Cleavage after residue', 'SP_score',
               'Fungi_Scores', 'Fungi_Prediction', 'Fungi_scores_Median',
               'Toxin_Scores', 'Toxin_Prediction', 'Toxin_scores_Median']
    df[columns] = pandas.DataFrame(df.Analysis_.tolist(), index=df.index)
    df.to_csv(Path(output_path) / path.with_suffix('.csv').name, index=None, sep='\t', columns=['Accession', 'Sequence'] + columns)


if __name__ == '__main__':

    args = get_args()
    if args.quiet:
        import warnings
        warnings.filterwarnings('ignore')
    pandarallel.initialize(nb_workers=args.ncores, progress_bar=True, use_memory_fs=False)

    files = sorted(list(Path(args.path).glob('*.fa')))
    for path in tqdm.tqdm(files):
        main(path, args.output, max_scan=args.max_scan, ncores=args.ncores)
