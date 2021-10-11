import itertools, sys
spinner = itertools.cycle(['-', '/', '|', '\\'])
def spin(name =""):
    sys.stdout.write(name+" "+next(spinner))   # write the next character
    sys.stdout.flush()                # flush stdout buffer (actual character display)
    sys.stdout.write('\b'*(len(name)+2))            # erase the last written char
