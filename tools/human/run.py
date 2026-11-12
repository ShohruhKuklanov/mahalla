import sys, traceback, os
sys.argv = sys.argv[1:]
try:
    exec(compile(open(sys.argv[0]).read(), sys.argv[0], 'exec'), {'__name__': '__main__'})
except SystemExit: raise
except BaseException:
    traceback.print_exc(); sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
