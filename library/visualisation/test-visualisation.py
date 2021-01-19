### test-visualisation v0.6

### MIT License

### Copyright (c) 2020 Kevin J. Walters

### Permission is hereby granted, free of charge, to any person obtaining a copy
### of this software and associated documentation files (the "Software"), to deal
### in the Software without restriction, including without limitation the rights
### to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
### copies of the Software, and to permit persons to whom the Software is
### furnished to do so, subject to the following conditions:

### The above copyright notice and this permission notice shall be included in all
### copies or substantial portions of the Software.

### THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
### IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
### FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
### AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
### LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
### OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
### SOFTWARE.


### This adds some hooks to a few tests then runs them to produce a visual
### representation of the state of pseudo serial object to create animations
### to help understand the tests

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from graphviz import Digraph
from dominate.tags import table, tr, td, font  ### html tag library

### This includes MockSerialArbitrary and PMS5003Simulator classes
### which are the ones that will be modified
from tests.test_setup import *


def add_hook(cls, method_name, pre=None, post=None):
    old_method = getattr(cls, method_name)
    def replacement_method(self, *args, **kwargs):
        if pre:
            pre(self, *args, **kwargs)
        rv = old_method(self, *args, **kwargs)
        if post:
            post(self, *args, **kwargs)
        return rv
    setattr(cls, method_name, replacement_method)
    return old_method


def restore_hook(cls, method_name, original_method):
    setattr(cls, method_name, original_method)


class TestVisualizerGV:
    hooked = {}
    NOBYTETEXT = "--"
    NOBUF = "  "
    EMPTY_COMMAND = ""

    def __init__(self, name, hook_classes):
        self._name = name

        self._frame = 1
        self._frame_gv = []
        self._gv_rx_buf_size = None
        self._gv_buffer = None
        self._gv_buflen = None
        self._gv_buf_width = None
        self._gv_buf_highlight = None
        self._gv_command = self.EMPTY_COMMAND
        self._serial_byte = None  # int
        self._xfer_serial_to_buffer = False
        self._xfer_buffer_to_command = False

        self._hook_classes = hook_classes
        for cls_to_hook in self._hook_classes:
            if not self.hooked.get(cls_to_hook):
                m0 = add_hook(cls_to_hook, "__init__",
                              post=self._constructor_posthook)
                m1 = add_hook(cls_to_hook, "simulate_rx",
                              post=self._simulate_rx_posthook)
                m2 = add_hook(cls_to_hook, "read",
                              pre=self._read_prehook,
                              post=self._read_posthook)
                self.hooked[cls_to_hook] = (("__init__", m0),
                                            ("simulate_rx", m1),
                                            ("read", m2))


    def _constructor_posthook(self, *args, **kwargs):

        obj = args[0]
        ### kwargs["rx_buf_size"] is not always set so fetch the
        ### rx_buf_size from the attribute and not kwargs["rx_buf_size"]
        self._gv_rx_buf_size = obj.rx_buf_size
        self._gv_buffer = bytearray(self._gv_rx_buf_size)
        self._gv_buflen = 0
        self._gv_buf_width = 16  ### TODO - this needs to be adaptive / look nice / maybe handle odd numbers


    def _simulate_rx_posthook(self, obj, data):

        for b in data:
            self._serial_byte = b
            if self._gv_buflen < self._gv_rx_buf_size:
                self._gv_buffer[self._gv_buflen] = b
                self._gv_buf_highlight = (self._gv_buflen, self._gv_buflen + 1)
                self._gv_buflen += 1
            else:
                self._gv_buf_highlight = None
            self.make_diagram()

        self._gv_buf_highlight = None
        self._serial_byte = None
        self.make_diagram()


    def _read_prehook(self, obj, length=None):

        bytes_to_read = min(length,
                            self._gv_buflen,
                            self._gv_rx_buf_size) if length else self._gv_buflen
        len_as_text = str(length) if length else ""

        ### Read data can end up long so split it across lines if
        ### necessary
        self._gv_buf_highlight = (0, bytes_to_read)
        enc_bytes_as_text = []
        chunk_size = 8
        for chunk_start in range(0, bytes_to_read, chunk_size):
            chunk_end = chunk_start + chunk_size
            if chunk_end > bytes_to_read:
                chunk_end = bytes_to_read
            chunk_bytes = bytes(self._gv_buffer[chunk_start:chunk_end])
            ### Escape backslash for graphviz
            enc_bytes_as_text.append(str(chunk_bytes).replace("\\", "\\\\"))

        if len(enc_bytes_as_text) == 0:
            enc_bytes_as_text.append("b''")

        ### Ensure there are at least four lines
        for _ in range(max(0, 4 - len(enc_bytes_as_text))):
            enc_bytes_as_text.append("")

        ### \l is \n with left justification in graphviz
        read_cmd = "read({:s}) = ".format(len_as_text)
        gv_cmd = (read_cmd + enc_bytes_as_text[0]
                  + "".join(["\\l" + (" " * len(read_cmd))
                             + l for l in enc_bytes_as_text[1:]]))
        self._gv_command = gv_cmd
        self.make_diagram()
        self._gv_buf_highlight = None


    def _read_posthook(self, obj, length=None):

        self._gv_buffer[:] = obj.buffer
        self._gv_buflen = obj.buflen
        self.make_diagram()  ### self._gc_command set in _read_prehook
        self._gv_command = self.EMPTY_COMMAND


    def __enter__(self):
        pass


    def __exit__(self, exc_type, exc_val, exc_tb):
        print("RENDER TIME")
        for gv in self._frame_gv:
            gv.render()
        print("RENDER DONE")
        self._unhook()


    def _unhook(self):
        for cls_to_unhook, orig_methods in self.hooked.items():
            for name, meth in orig_methods:
                restore_hook(cls_to_unhook, name, meth)
        self.hooked.clear()


    @classmethod
    def _make_table(cls, buf, buf_valid_len, width, highlight=None):

        html_table = table(border="1", cellborder="0")
        n_rows = math.ceil(len(buf) / width)
        with html_table:
            buf_idx = 0
            for _ in range(n_rows):
                row = tr()
                for col in range(width):
                    cell_text = "{:02x}".format(buf[buf_idx]) if buf_idx < len(buf) else cls.NOBUF
                    port = "port_{:03d}".format(buf_idx)
                    fmt_cell_text = cell_text if buf_idx < buf_valid_len else font(cell_text,
                                                                                   color="lightgrey")
                    extraargs = {"port": port}
                    if highlight and highlight[0] <= buf_idx < highlight[1]:
                        extraargs["bgcolor"] = "yellow"

                    row.add(td(fmt_cell_text, **extraargs))
                    buf_idx += 1

        ### <td> entries end up wide with the whitespace if pretty is True
        return html_table.render(pretty=False)


    def make_diagram(self):
        tl = Digraph('structs',
                     filename="frame-{:s}-{:04d}.gv".format(self._name,
                                                            self._frame),
                     format='png',
                     node_attr={'shape': 'none', "fontname": "Courier"})

        with tl.subgraph(name="child0") as lab:
            lab.node("textline1", "RX wire")
            lab.node("textline2", "Buffer \llen {:3s}".format(str(self._gv_rx_buf_size)))
            lab.node("textline3", "Command")
            lab.edge("textline1", "textline2", style="invis")
            lab.edge("textline2", "textline3", style="invis")

        with tl.subgraph(name="child1") as d:
            gvbufrepr = self._make_table(self._gv_buffer, self._gv_buflen,
                                         width=self._gv_buf_width,
                                         highlight=self._gv_buf_highlight)

            d.node('buffer', "<\n" + gvbufrepr + ">", width="6")  ### html appears to go inside extra angle brackets

            if self._serial_byte is None:
                d.node('serial', self.NOBYTETEXT,
                       labelfontcolor="gray", style="rounded", shape="box")
            else:
                d.node('serial', "{:02x}".format(self._serial_byte),
                       style="rounded", shape="box", weight="0")
                if self._gv_buf_highlight:
                    d.edges([("serial", "buffer:port_{:03d}:n".format(self._gv_buf_highlight[0]))])

            d.edge("serial", "buffer", style="invis", weight="10000")  ### helps with positioning
            #d.node('command', 'read({:d}) = "aabbcc"'.format(32), color="white")

            ### TODO - maybe construct command box so it always has same width 14+4*8  ?

            d.node('command', self._gv_command if self._gv_command else " \n \n \n ", shape="none")

            if self._gv_buf_highlight and self._gv_command:
                d.edge("buffer:" + "port_000:w", "command:w", color="blue", weight="0")
            d.edge("buffer", "command", style="invis", weight="10000")

        self._frame_gv.append(tl)
        self._frame += 1


with TestVisualizerGV("buffer_full_badframelen_short", (MockSerialArbitrary, PMS5003Simulator)):
    ### MockSerialArbitrary based
    test_buffer_full_badframelen_short()


### THIS SPITS WAY TOO MANY FRAMES!
#with TestVisualizerGV("active_mode_to_passive_unlucky", (MockSerialArbitrary, PMS5003Simulator)):
#    ### PMS5003Simulator based
#    test_active_mode_to_passive_unlucky()  ### this works ok


with TestVisualizerGV("test_odd_zero_burst", (MockSerialArbitrary, PMS5003Simulator)):
    ### PMS5003Simulator based
    test_odd_zero_burst()
