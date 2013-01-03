# Copyright (c) 2008-2011 Tim Newsham, Andrey Mirtchovski
# Copyright (c) 2011-2012 Peter V. Saveliev
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import py9p
import threading
import struct


class Marshal(object):
    chatty = 0
    position = 0

    def setBuf(self, s=""):
        self.position = 0
        self.bytes = s

    def getBuf(self):
        return self.bytes

    def _checkSize(self, v, mask):
        if v != v & mask:
            raise py9p.Error("Invalid value %d" % v)

    def _checkLen(self, x, l):
        if len(x) != l:
            raise py9p.Error("Wrong length %d, expected %d: %r" % (
                len(x), l, x))

    def encX(self, x):
        "Encode opaque data"
        self.bytes += x

    def decX(self, l):
        if len(self.bytes[self.position:]) < l:
            raise py9p.Error("buffer exhausted")
        p = self.position
        self.position += l
        return self.bytes[p:p + l]

    def enc1(self, x):
        "Encode a 1-byte integer"
        self.bytes += struct.pack('B', x)

    def dec1(self):
        return struct.unpack('b', self.decX(1))[0]

    def enc2(self, x):
        "Encode a 2-byte integer"
        self.bytes += struct.pack('H', x)

    def dec2(self):
        return struct.unpack('H', self.decX(2))[0]

    def enc4(self, x):
        "Encode a 4-byte integer"
        self.bytes += struct.pack('I', x)

    def dec4(self):
        return struct.unpack('I', self.decX(4))[0]

    def enc8(self, x):
        "Encode a 8-byte integer"
        self.bytes += struct.pack('Q', x)

    def dec8(self):
        return struct.unpack('Q', self.decX(8))[0]

    def encS(self, x):
        "Encode length/data strings with 2-byte length"
        self.bytes += struct.pack("H", len(x))
        self.bytes += x

    def decS(self):
        return self.decX(self.dec2())

    def encD(self, d):
        "Encode length/data arrays with 4-byte length"
        self.bytes += struct.pack("I", len(d))
        self.bytes += d

    def decD(self):
        return self.decX(self.dec4())


class Marshal9P(Marshal):
    MAXSIZE = 1024 * 1024            # XXX
    chatty = False

    def __init__(self, dotu=0, chatty=False):
        self.chatty = chatty
        self.dotu = dotu
        self._lock = threading.Lock()

    def encQ(self, q):
        self.bytes += struct.pack("=BIQ", q.type, q.vers, q.path)

    def decQ(self):
        return py9p.Qid(self.dec1(), self.dec4(), self.dec8())

    def _checkType(self, t):
        if t not in py9p.cmdName:
            raise py9p.Error("Invalid message type %d" % t)

    def _checkResid(self):
        if len(self.bytes) > self.position:
            raise py9p.Error("Extra information in message: %r" % self.bytes)

    def send(self, fd, fcall):
        "Format and send a message"
        with self._lock:
            self.setBuf()
            self._checkType(fcall.type)
            if self.chatty:
                print "-%d->" % fd.fileno(), py9p.cmdName[fcall.type], \
                    fcall.tag, fcall.tostr()
            self.enc(fcall)
            fd.write(struct.pack("I", len(self.bytes) + 4) + self.bytes)

    def recv(self, fd):
        "Read and decode a message"
        with self._lock:
            self.setBuf(fd.read(4))
            size = self.dec4()
            if size > self.MAXSIZE or size < 4:
                raise py9p.Error("Bad message size: %d" % size)
            self.setBuf(fd.read(size - 4))
            type, tag = self.dec1(), self.dec2()
            self._checkType(type)
            fcall = py9p.Fcall(type, tag)
            self.dec(fcall)
            self._checkResid()
            if self.chatty:
                print "<-%d- %s %s %s" % (fd.fileno(), py9p.cmdName[type],
                        tag, fcall.tostr())
            return fcall

    def encstat(self, fcall, enclen=1):
        statsz = 0
        if enclen:
            for x in fcall.stat:
                if self.dotu:
                    statsz = 2 + 4 + 13 + 4 + 4 + 4 + 8 + \
                            len(x.name) + len(x.uid) + len(x.gid) + \
                            len(x.muid) + 2 + 2 + 2 + 2 + \
                            len(x.extension) + 2 + 4 + 4 + 4
                else:
                    statsz = 2 + 4 + 13 + 4 + 4 + 4 + 8 + \
                            len(x.name) + len(x.uid) + len(x.gid) + \
                            len(x.muid) + 2 + 2 + 2 + 2
            self.enc2(statsz + 2)

        for x in fcall.stat:
            self.enc2(statsz)
            self.enc2(x.type)
            self.enc4(x.dev)
            self.encQ(x.qid)
            self.enc4(x.mode)
            self.enc4(x.atime)
            self.enc4(x.mtime)
            self.enc8(x.length)
            self.encS(x.name)
            self.encS(x.uid)
            self.encS(x.gid)
            self.encS(x.muid)
            if self.dotu:
                self.encS(x.extension)
                self.enc4(x.uidnum)
                self.enc4(x.gidnum)
                self.enc4(x.muidnum)

    def enc(self, fcall):
        self.enc1(fcall.type)
        self.enc2(fcall.tag)
        if fcall.type in (py9p.Tversion, py9p.Rversion):
            self.enc4(fcall.msize)
            self.encS(fcall.version)
        elif fcall.type == py9p.Tauth:
            self.enc4(fcall.afid)
            self.encS(fcall.uname)
            self.encS(fcall.aname)
            if self.dotu:
                self.enc4(fcall.uidnum)
        elif fcall.type == py9p.Rauth:
            self.encQ(fcall.aqid)
        elif fcall.type == py9p.Rerror:
            self.encS(fcall.ename)
            if self.dotu:
                self.enc4(fcall.errno)
        elif fcall.type == py9p.Tflush:
            self.enc2(fcall.oldtag)
        elif fcall.type == py9p.Tattach:
            self.enc4(fcall.fid)
            self.enc4(fcall.afid)
            self.encS(fcall.uname)
            self.encS(fcall.aname)
            if self.dotu:
                self.enc4(fcall.uidnum)
        elif fcall.type == py9p.Rattach:
            self.encQ(fcall.qid)
        elif fcall.type == py9p.Twalk:
            self.enc4(fcall.fid)
            self.enc4(fcall.newfid)
            self.enc2(len(fcall.wname))
            for x in fcall.wname:
                self.encS(x)
        elif fcall.type == py9p.Rwalk:
            self.enc2(len(fcall.wqid))
            for x in fcall.wqid:
                self.encQ(x)
        elif fcall.type == py9p.Topen:
            self.enc4(fcall.fid)
            self.enc1(fcall.mode)
        elif fcall.type in (py9p.Ropen, py9p.Rcreate):
            self.encQ(fcall.qid)
            self.enc4(fcall.iounit)
        elif fcall.type == py9p.Tcreate:
            self.enc4(fcall.fid)
            self.encS(fcall.name)
            self.enc4(fcall.perm)
            self.enc1(fcall.mode)
            if self.dotu:
                self.encS(fcall.extension)
        elif fcall.type == py9p.Tread:
            self.enc4(fcall.fid)
            self.enc8(fcall.offset)
            self.enc4(fcall.count)
        elif fcall.type == py9p.Rread:
            self.encD(fcall.data)
        elif fcall.type == py9p.Twrite:
            self.enc4(fcall.fid)
            self.enc8(fcall.offset)
            self.enc4(len(fcall.data))
            self.encX(fcall.data)
        elif fcall.type == py9p.Rwrite:
            self.enc4(fcall.count)
        elif fcall.type in (py9p.Tclunk,  py9p.Tremove, py9p.Tstat):
            self.enc4(fcall.fid)
        elif fcall.type in (py9p.Rstat, py9p.Twstat):
            if fcall.type == py9p.Twstat:
                self.enc4(fcall.fid)
            self.encstat(fcall, 1)

    def decstat(self, fcall, enclen=0):
        fcall.stat = []
        if enclen:
            # feed 2 bytes of total size
            self.dec2()
        while len(self.bytes) - self.position:
            size = self.dec2()

            stat = py9p.Dir(self.dotu)
            stat.type = self.dec2()     # type
            stat.dev = self.dec4()      # dev
            stat.qid = self.decQ()      # qid
            stat.mode = self.dec4()     # mode
            stat.atime = self.dec4()    # atime
            stat.mtime = self.dec4()    # mtime
            stat.length = self.dec8()   # length
            stat.name = self.decS()     # name
            stat.uid = self.decS()      # uid
            stat.gid = self.decS()      # gid
            stat.muid = self.decS()     # muid
            if self.dotu:
                stat.extension = self.decS()
                stat.uidnum = self.dec4()
                stat.gidnum = self.dec4()
                stat.muidnum = self.dec4()
            fcall.stat.append(stat)

    def dec(self, fcall):
        if fcall.type in (py9p.Tversion, py9p.Rversion):
            fcall.msize = self.dec4()
            fcall.version = self.decS()
        elif fcall.type == py9p.Tauth:
            fcall.afid = self.dec4()
            fcall.uname = self.decS()
            fcall.aname = self.decS()
            if self.dotu:
                fcall.uidnum = self.dec4()
        elif fcall.type == py9p.Rauth:
            fcall.aqid = self.decQ()
        elif fcall.type == py9p.Rerror:
            fcall.ename = self.decS()
            if self.dotu:
                fcall.errno = self.dec4()
        elif fcall.type == py9p.Tflush:
            fcall.oldtag = self.dec2()
        elif fcall.type == py9p.Tattach:
            fcall.fid = self.dec4()
            fcall.afid = self.dec4()
            fcall.uname = self.decS()
            fcall.aname = self.decS()
            if self.dotu:
                fcall.uidnum = self.dec4()
        elif fcall.type == py9p.Rattach:
            fcall.qid = self.decQ()
        elif fcall.type == py9p.Twalk:
            fcall.fid = self.dec4()
            fcall.newfid = self.dec4()
            fcall.nwname = self.dec2()
            fcall.wname = [self.decS() for n in xrange(fcall.nwname)]
        elif fcall.type == py9p.Rwalk:
            fcall.nwqid = self.dec2()
            fcall.wqid = [self.decQ() for n in xrange(fcall.nwqid)]
        elif fcall.type == py9p.Topen:
            fcall.fid = self.dec4()
            fcall.mode = self.dec1()
        elif fcall.type in (py9p.Ropen, py9p.Rcreate):
            fcall.qid = self.decQ()
            fcall.iounit = self.dec4()
        elif fcall.type == py9p.Tcreate:
            fcall.fid = self.dec4()
            fcall.name = self.decS()
            fcall.perm = self.dec4()
            fcall.mode = self.dec1()
            if self.dotu:
                fcall.extension = self.decS()
        elif fcall.type == py9p.Tread:
            fcall.fid = self.dec4()
            fcall.offset = self.dec8()
            fcall.count = self.dec4()
        elif fcall.type == py9p.Rread:
            fcall.data = self.decD()
        elif fcall.type == py9p.Twrite:
            fcall.fid = self.dec4()
            fcall.offset = self.dec8()
            fcall.count = self.dec4()
            fcall.data = self.decX(fcall.count)
        elif fcall.type == py9p.Rwrite:
            fcall.count = self.dec4()
        elif fcall.type in (py9p.Tclunk, py9p.Tremove, py9p.Tstat):
            fcall.fid = self.dec4()
        elif fcall.type in (py9p.Rstat, py9p.Twstat):
            if fcall.type == py9p.Twstat:
                fcall.fid = self.dec4()
            self.decstat(fcall, 1)

        return fcall
