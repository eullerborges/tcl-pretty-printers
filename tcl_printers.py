"""
Implementation of Tcl pretty-printers.

This implementations tries its best to avoid calling functions and using
symbols that might be unavailable on optimized builds. The containers are
printed in a similar way to STL containers with their default pretty printers.
"""
import gdb


# Auxiliary lambdas to lookup some of the needed types in GDB.
# This has to be done through lambdas because for some reason setting this
# upfront does not work properly: casting renders incorrect/inconsistent results.
INT_T = lambda: gdb.lookup_type("int")
HASH_TABLE_T = lambda: gdb.lookup_type("Tcl_HashTable")
HASH_ENTRY_T = lambda: gdb.lookup_type("Tcl_HashEntry")
VOID_PP_T = lambda: gdb.lookup_type("void").pointer().pointer()
VOID_P_T = lambda: gdb.lookup_type("void").pointer()
TCL_OBJ_P_T = lambda: gdb.lookup_type("Tcl_Obj").pointer()
TCL_OBJ_PP_T = lambda: gdb.lookup_type("Tcl_Obj").pointer().pointer()

class TclObjPrinter(object):
    """
    Default printer for a Tcl object.

    Objects without specific internal representation (basic strings) or
    without a pretty-printer implementation will use this printer.

    This tries to use the existing string representation of the object if the
    representation is valid. Otherwise, this will use Tcl_GetString to force
    the representation generation.
    """
    def __init__(self, val):
        self.val = val

    def to_string(self):
        bytes_val = self.val["bytes"]
        if int(bytes_val):
            # Return the still-valid string representation
            return bytes_val
        else:
            # Use Tcl_GetString to force the string representation
            return gdb.parse_and_eval("(const char*)Tcl_GetString({})".format(int(self.val.address))).string()

    def display_hint(self):
        return "string"

class TclIntPrinter(TclObjPrinter):
    """
    Default printer for Tcl's int, long, boolean, and possibly Tcl_WideInt.

    Note that Tcl does not really differentiate long or boolean from int on
    8.6, and thus these types will be handled by this printer.

    Tcl_WideInt might be a C 'long' under the hood if TCL_WIDE_INT_IS_LONG was
    set during the compilation and will be handled by this printer in that
    case.

    NOTE: Tcl booleans parsed from strings could possibly be handled by another
    printer since they have a different type ("booleanString") and can thus be
    differentiated to a C++ bool. The issue with that would be the
    inconsistency with bools created by Tcl_NewBooleanObj, which have an
    integer representation. As even the former have a valid integer
    representation after the parsing, they're not differentiated in this
    implementation.
    """
    def to_string(self):
        return self.val["internalRep"]["longValue"]

class TclDoublePrinter(TclObjPrinter):
    def to_string(self):
        return self.val["internalRep"]["doubleValue"]

class TclListPrinter(object):
    """
    Printer for Tcl Lists.

    We do some pointer arithmetic in this class to make up for the fact that we
    don't know the List structs, which corresponds to the internal
    representation of the Tcl list.

    This implementation considers the following internal representation for the list:
    typedef struct List {
        int refCount;
        int maxElemCount;
        int elemCount;
        int canonicalFlag;
        Tcl_Obj *elements;
    } List;

    Internal list array: (Tcl_Obj**)($list.internalRep.twoPtrValue.ptr1 + 4*sizeof(int))
    List element: *(Tcl_Obj*)$list_array[<index>]
    """
    def __init__(self, val):
        self.internal_rep_val = val["internalRep"]["twoPtrValue"]["ptr1"]
        # The size is the third integer of the List struct
        self.size = int((self.internal_rep_val + 2*INT_T().sizeof).cast(INT_T().pointer()).dereference())

    def to_string(self):
        return ("Tcl List of length {}".format(self.size))

    class _iterator(object):
        def __init__(self, obj_array_val, list_size):
            self.obj_array_val = obj_array_val
            self.size = list_size
            self.count = 0

        def __iter__(self):
            return self

        def next(self):
            return type(self).__next__(self)

        def __next__(self):
            if self.count >= self.size:
                raise StopIteration

            # Calculating the pointer for the next element
            elem_ptr = self.obj_array_val + self.count

            key = elem_ptr.dereference().dereference()
            count = self.count
            self.count += 1
            return ("elem {}".format(count), key)

    def children(self):
        if not self.size:
            return []

        # The object array is offset by 4 integers on the List struct.
        obj_array_val = (self.internal_rep_val + 4*INT_T().sizeof).cast(TCL_OBJ_PP_T())

        return self._iterator(obj_array_val, self.size)

    def display_hint (self):
        return 'array'

class TclDictPrinter(object):
    """
    Printer for Tcl Dictionaries.

    We do some pointer arithmetic in this class to make up for the fact that we
    don't know the Dict and ChainEntry structs, which correspond to the
    internal representation of the dictionary and the ordered entries of the
    dictionary hash table (respectively).

    The chain entries are arranged in a doubly-linked list, and the head of
    this list is available on the Dict structure. The last element has the next
    pointer set to NULL.

    This implementation considers the following internal representation for the dictionary:
    typedef struct Dict {
        Tcl_HashTable table;
        ChainEntry *entryChainHead;
        ChainEntry *entryChainTail;
        [...]
    } Dict;

    Start ChainEntry pointer : (*(void**)($dict.internalRep.twoPtrValue.ptr1 + sizeof(Tcl_HashTable)))
    First Tcl_HashEntry entry: *(Tcl_HashEntry*)$chain_entry
    HashEntry Key: *(Tcl_Obj*)$hash_entry.key.oneWordValue
    HashEntry Value: *(Tcl_Obj*)$hash_entry.clientData
    """
    def __init__(self, val):
        self.internal_rep = val["internalRep"]["twoPtrValue"]["ptr1"]
        # The first element of the Dict internal representation is the hash table
        self.size = int(self.internal_rep.cast(HASH_TABLE_T().pointer()).dereference()["numEntries"])

    class _iterator(object):
        def __init__(self, dict_internal_rep_ptr):
            # This is Dict::entryChainHead
            offset = (dict_internal_rep_ptr + HASH_TABLE_T().sizeof)
            self.entryChainHeadPtr = offset.cast(VOID_PP_T()).dereference()
            # Used to keep track of the iteration on the ChainEntry elements.
            self.curChainEntryPtr = self.entryChainHeadPtr
            self.is_key_iter = True

        def __iter__(self):
            return self

        def next(self):
            return type(self).__next__(self)

        def __next__(self):
            if not int(self.curChainEntryPtr):
                raise StopIteration

            # The Tcl_HashEntry is the first element of ChainEntry
            hash_entry = self.curChainEntryPtr.cast(HASH_ENTRY_T().pointer()).dereference()

            # We iterate key, value, key, value...
            if self.is_key_iter:
                self.is_key_iter = False
                key = hash_entry["key"]["oneWordValue"].cast(TCL_OBJ_P_T()).dereference()
                # First tuple element below is not really used with the map hint, only the second.
                return ("key", key)
            else:
                self.is_key_iter = True
                value = hash_entry["clientData"].cast(TCL_OBJ_P_T()).dereference()
                # The nextPtr is the third element of the ChainEntry structure,
                # after the hash entry and the pointer to the previous element.
                pointer_size = VOID_P_T().sizeof
                self.curChainEntryPtr = (self.curChainEntryPtr + HASH_ENTRY_T().sizeof \
                                         + pointer_size).cast(VOID_PP_T()).dereference()
                # First tuple element below is not really used with the map hint, only the second.
                return ("value", value)


    def to_string(self):
        return ("Tcl Dict with {} elements".format(self.size))

    def children(self):
        return self._iterator(self.internal_rep)

    def display_hint (self):
        return 'map'

def tcl_lookup_function(val):
    """
    This lookup functions determines what pretty printers should be used for
    which Tcl object, and returns the instantiated printer.
    """
    lookup_tag = val.type.tag
    if lookup_tag is None:
        return
    if lookup_tag == "Tcl_Obj":
        type_field_val = val["typePtr"]
        type_name = ""
        if int(type_field_val) != 0:
            type_name = type_field_val["name"].string()

        if type_name == "list":
            return TclListPrinter(val)
        elif type_name == "dict":
            return TclDictPrinter(val)
        elif type_name in ["int", "booleanString"]:
            return TclIntPrinter(val)
        elif type_name == "double":
            return TclDoublePrinter(val)
        else:
            return TclObjPrinter(val)


def register_tcl_printers(objfile):
    """
    Registers the pretty printers for the Tcl objects on gdb.
    """
    if not objfile:
        objfile = gdb
    objfile.pretty_printers.append(tcl_lookup_function)
