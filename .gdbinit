# This is a sample file with the necessary bits to add to gdbinit to make the pretty printers work.
python
import sys

sys.path.append('/path/to/tcl-pretty-printers')
from tcl_printers import register_tcl_printers
register_tcl_printers(None)

end
