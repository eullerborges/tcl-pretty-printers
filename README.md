# tcl-pretty-printers
This repository provides GDB pretty printers for Tcl objects of the [Tcl C API](https://www.tcl.tk/man/tcl8.6/TclLib/contents.htm) (i.e., `Tcl_Obj` structures).

The pretty printers use implementation details of the Tcl library to support printing Tcl containers, strings, and numerals just like [libstdc++ pretty printers](https://www.tcl.tk/man/tcl8.6/TclLib/contents.htm).

The exemple below shows how the pretty printers work for a Tcl dictionary that contains different types of Tcl objects:
~~~ gdb
(gdb) set print pretty on               # Use indentation to print map elements   
(gdb) set print array on                # Use indentation to print array elements
(gdb) p *tobjPtr
$1 = Tcl Dict with 9 elements = {
  ["key"] = "value",
  ["nested list"] = Tcl List of length 3 = {
    "elem1",
    "elem2",
    Tcl List of length 2 = {
      "nested.sublist.elem1",
      "nested.sublist.elem2"
    }
  },
  ["myint"] = 42,
  ["mylong"] = 4611686018427387904,
  ["mywide"] = 20,
  ["mybool"] = 1,
  ["mydouble"] = 3.1400000000000001,
  [2.7182818284499999] = "double_as_key",
  ["nested_dict"] = Tcl Dict with 2 elements = {
    ["foo"] = 1,
    [Tcl List of length 3 = {
      "nested",
      "list",
      "key"
    }] = 1
  }
}

~~~

To use the pretty printers, clone this repository to some common location and add the following to your `~/.gdbinit` file:
``` gdbinit
python                                                   
import sys
# This is a sample file with the necessary bits to add to gdbinit to make the pretty printers work
sys.path.append('/path/to/tcl-pretty-printers')
from tcl_printers import register_tcl_printers
register_tcl_printers(None)                                                                                                                                                                   
end                                                                                               
```
