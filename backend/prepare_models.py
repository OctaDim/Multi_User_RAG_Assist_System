#!/usr/bin/env python3
"""Prepare the complete pinned model set explicitly, independently of main."""
import argparse
import sys

from app.model_artifacts import ModelArtifactError, prepare_models


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source', help='existing full model directory (copied by default)')
    mode.add_argument('--download', action='store_true', help='download all pinned artifacts explicitly')
    parser.add_argument('--move', action='store_true', help='remove verified source companions only after destination verification')
    arguments = parser.parse_args(argv)
    if arguments.move and not arguments.source:
        parser.error('--move requires --source')
    try:
        paths = prepare_models(source=arguments.source, download=arguments.download, move=arguments.move)
    except ModelArtifactError as error:
        print(error, file=sys.stderr)
        return 1
    print(f'Verified {len(paths)} model artifacts in project rag/local_models/')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
