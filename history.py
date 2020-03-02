import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    filepath = sys.argv[1]

    print('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
          '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">')
    print('<html xmlns="http://www.w3.org/1999/xhtml" xmlns="http://www.w3.org/1999/html">')
    print('<head></head>')
    print('<body>')

    with open(filepath) as f:
        for line in f.readlines():
            parts = line.strip().split('\t')
            print(f'<a href="{parts[0]}"><img src="{parts[1]}"/></a>')

    print('</body>')
    print('</html>')