#!/usr/bin/env python

"""Simple harness that benchmarks different variants of the routines,
caches the results, and emits all of the records at the end.

Results are generated for different values of:
 * Source
 * Routine
 * Length
 * Alignment
"""

import argparse
import subprocess
import math
import sys

SINGLE_BUFFER_FUNCTIONS = ['strchr', 'memset', 'strlen', 'memchr']
DUAL_BUFFER_FUNCTIONS = ['memcmp', 'memcpy', 'strcmp', 'strcpy']

FUNCTIONS = list(SINGLE_BUFFER_FUNCTIONS)
FUNCTIONS.extend(DUAL_BUFFER_FUNCTIONS)

HAS = {
    'this': 'bounce memchr memcpy memset strchr strcpy strlen',
    'bionic-a9': 'memcmp memcpy memset strcmp strcpy strlen',
    'bionic-a15': 'memcmp memcpy memset strcmp strcpy strlen',
    'bionic-c': FUNCTIONS,
    'csl': 'memcpy memset',
    'glibc': 'memcpy memset strchr strlen',
    'glibc-c': FUNCTIONS,
    'newlib': 'memcpy strcmp strcpy strlen',
    'newlib-c': FUNCTIONS,
    'newlib-xscale': 'memchr memcpy memset strchr strcmp strcpy strlen',
    'plain': 'memset memcpy strcmp strcpy',
}

ALIGNMENTS = {
    'bounce': ['1'],
}

VARIANTS = sorted(HAS.keys())

NUM_RUNS = 5

DRY_RUN = False

#CLI helpers
def parse_alignments(alignment):
    e = Exception("Alignments must be expressed as colon-separated digits e.g. 8:32 16:16")
    alignments = alignment.split(':')
    if len(alignments) != 2:
        raise e
    try:
        [int(x) for x in alignments]
    except:
        raise e
    return alignment


def run(cache, variant, function, bytes, loops, alignment, run_id, quiet=False):
    """Perform a single run, exercising the cache as appropriate."""
    key = ':'.join('%s' % x for x in (variant, function, bytes, loops, alignment, run_id))

    if key in cache:
        got = cache[key]
    else:
        xbuild = build + "/try-"
        cmd = '%(xbuild)s%(variant)s -t %(function)s -c %(bytes)s -l %(loops)s -a %(alignment)s -r %(run_id)s' % locals()

        if(DRY_RUN):
            print cmd
            return 1
        else:
            try:
                got = subprocess.check_output(cmd.split()).strip()
            except OSError, ex:
                assert False, 'Error %s while running %s' % (ex, cmd)

    parts = got.split(':')
    took = float(parts[7])

    cache[key] = got

    if not quiet:
        print got
        sys.stdout.flush()

    return took

def run_many(cache, variants, bytes, all_functions):
    # We want the data to come out in a useful order.  So fix an
    # alignment and function, and do all sizes for a variant first
    bytes = sorted(bytes)
    mid = bytes[int(len(bytes)/1.5)]

    if not all_functions:
        # Use the ordering in 'this' as the default
        all_functions = HAS['this'].split()

        # Find all other functions
        for functions in HAS.values():
            for function in functions.split():
                if function not in all_functions:
                    all_functions.append(function)

    for function in all_functions:
        for alignment in ALIGNMENTS[function]:
            for variant in variants:
                if function not in HAS[variant].split():
                    continue

                # Run a tracer through and see how long it takes and
                # adjust the number of loops based on that.  Not great
                # for memchr() and similar which are O(n), but it will
                # do
                f = 50000000
                want = 5.0

                loops = int(f / math.sqrt(max(1, mid)))
                took = run(cache, variant, function, mid, loops, alignment, 0,
                           quiet=True)
                # Keep it reasonable for silly routines like bounce
                factor = min(20, max(0.05, want/took))
                f = f * factor
                
                # Round f to a few significant figures
                scale = 10**int(math.log10(f) - 1)
                f = scale*int(f/scale)

                for b in sorted(bytes):
                    # Figure out the number of loops to give a roughly consistent run
                    loops = int(f / math.sqrt(max(1, b)))
                    for run_id in range(0, NUM_RUNS):
                        run(cache, variant, function, b, loops, alignment,
                            run_id)

def run_top(cache):
    parser = argparse.ArgumentParser()
    #Syntax: python ../cortex-strings/scripts/bench.py -f bounce memcpy -v this glibc
    parser.add_argument("-v", "--variants", nargs="+", help="library variant to run (run all if not specified)", default = VARIANTS, choices = VARIANTS)
    parser.add_argument("-f", "--functions", nargs="+", help="function to run (run all if not specified)", default = FUNCTIONS, choices = FUNCTIONS)
    parser.add_argument("-u", "--upper", type=int, help="upper limit to test to (in bytes)", default = 512*1024)
    parser.add_argument("-l", "--lower", type=int, help="lowest block size to test (bytes)", default = 0)
    parser.add_argument("-s", "--steps", nargs="+", help="steps to test powers of", default = ['1.4', '2.0'])
    parser.add_argument("-p", "--prefix", help="path to executables, relative to CWD", default=".")
    parser.add_argument("-d", "--dry-run", help="Dry run: just print the invocations that we would use", default=False, action="store_true")
    parser.add_argument("-a", "--alignments", nargs="+", type=parse_alignments, help="Alignments, e.g. 2:32 for 2-byte-aligned source to 4-byte-aligned dest. Functions with just a dest use the number before the colon.", default=['1:32', '2:32', '4:32', '8:32', '16:32', '32:32'])
    args = parser.parse_args()

    if(args.lower >= args.upper):
      raise Exception("Range starts after it ends!")

    global build, DRY_RUN, ALIGNMENTS
    build = args.prefix
    DRY_RUN = args.dry_run
    for function in SINGLE_BUFFER_FUNCTIONS:
        ALIGNMENTS[function] = [x.split(':')[0] for x in args.alignments]
    for function in DUAL_BUFFER_FUNCTIONS:
        ALIGNMENTS[function] = args.alignments

    bytes = []
    
    #Test powers of steps
    for step in args.steps:
        if step[0] == '+':
            step = int(step[1:])
            bytes.extend(range(args.lower, args.upper + step, step))
        else:
            step = float(step)
            steps = int(round(math.log(args.upper - args.lower, step)))
            bytes.extend([args.lower - 1 + int(step**x) for x in range(steps+1)])

    run_many(cache, args.variants, bytes, args.functions)

def main():
    cachename = 'cache.txt'

    cache = {}

    try:
        with open(cachename) as f:
            for line in f:
                line = line.strip()
                parts = line.split(':')
                cache[':'.join(parts[:7])] = line
    except:
        pass

    try:
        run_top(cache)
    finally:
        with open(cachename, 'w') as f:
            for line in sorted(cache.values()):
                print >> f, line

if __name__ == '__main__':
    main()
