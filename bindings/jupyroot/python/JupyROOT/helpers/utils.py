# -*- coding:utf-8 -*-

#-----------------------------------------------------------------------------
#  Author: Danilo Piparo <Danilo.Piparo@cern.ch> CERN
#-----------------------------------------------------------------------------

################################################################################
# Copyright (C) 1995-2020, Rene Brun and Fons Rademakers.                      #
# All rights reserved.                                                         #
#                                                                              #
# For the licensing terms see $ROOTSYS/LICENSE.                                #
# For the list of contributors see $ROOTSYS/README/CREDITS.                    #
################################################################################


from __future__ import print_function

import re
import sys
import time
from datetime import datetime
from hashlib import sha1
from subprocess import check_output

import IPython.display
import ROOT
from IPython import get_ipython
from IPython.core.extensions import ExtensionManager
from IPython.display import HTML
from JupyROOT import canvas, interactive
from JupyROOT.helpers import handlers

# We want iPython to take over the graphics
ROOT.gROOT.SetBatch()


cppMIME = 'text/x-c++src'

_jsMagicHighlight = """
Jupyter.CodeCell.options_default.highlight_modes['magic_{cppMIME}'] = {{'reg':[/^%%cpp/]}};
console.log("JupyROOT - %%cpp magic configured");
"""

def _getPlatform():
    return sys.platform

def _getLibExtension(thePlatform):
    '''Return appropriate file extension for a shared library
    >>> _getLibExtension('darwin')
    '.dylib'
    >>> _getLibExtension('win32')
    '.dll'
    >>> _getLibExtension('OddPlatform')
    '.so'
    '''
    pExtMap = {
        'darwin' : '.dylib',
        'win32'  : '.dll'
    }
    return pExtMap.get(thePlatform, '.so')

def welcomeMsg():
    print("Welcome to JupyROOT %s" %ROOT.gROOT.GetVersion())

def commentRemover( text ):
   '''
   >>> s="// hello"
   >>> commentRemover(s)
   ''
   >>> s="int /** Test **/ main() {return 0;}"
   >>> commentRemover(s)
   'int  main() {return 0;}'
   '''
   def blotOutNonNewlines( strIn ) :  # Return a string containing only the newline chars contained in strIn
      return "" + ("\n" * strIn.count('\n'))

   def replacer( match ) :
      s = match.group(0)
      if s.startswith('/'):  # Matched string is //...EOL or /*...*/  ==> Blot out all non-newline chars
         return blotOutNonNewlines(s)
      else:                  # Matched string is '...' or "..."  ==> Keep unchanged
         return s

   pattern = re.compile(\
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE)

   return re.sub(pattern, replacer, text)


# Here functions are defined to process C++ code
def processCppCodeImpl(code):
    #code = commentRemover(code)
    ROOT.gInterpreter.ProcessLine(code)

def processMagicCppCodeImpl(code):
    err = ROOT.ProcessLineWrapper(code)
    if err == ROOT.TInterpreter.kProcessing:
        ROOT.gInterpreter.ProcessLine('.@')
        ROOT.gInterpreter.ProcessLine('cerr << "Unbalanced braces. This cell was not processed." << endl;')

def declareCppCodeImpl(code):
    #code = commentRemover(code)
    ROOT.gInterpreter.Declare(code)

def processCppCode(code):
    processCppCodeImpl(code)

def processMagicCppCode(code):
    processMagicCppCodeImpl(code)

def declareCppCode(code):
    declareCppCodeImpl(code)

def _checkOutput(command,errMsg=None):
    out = ""
    try:
        out = check_output(command.split())
    except:
        if errMsg:
            sys.stderr.write("%s (command was %s)\n" %(errMsg,command))
    return out

def _invokeAclicMac(fileName):
    '''FIXME!
    This function is a workaround. On osx, it is impossible to link against
    libzmq.so, among the others. The error is known and is
    "ld: can't link with bundle (MH_BUNDLE) only dylibs (MH_DYLIB)"
    We cannot at the moment force Aclic to change the linker command in order
    to exclude these libraries, so we launch a second root session to compile
    the library, which we then load.
    '''
    command = 'root -l -q -b -e gSystem->CompileMacro(\"%s\",\"k\")*0'%fileName
    out = _checkOutput(command, "Error ivoking ACLiC")
    libNameBase = fileName.replace(".C","_C")
    ROOT.gSystem.Load(libNameBase)

def _codeToFilename(code):
    '''Convert code to a unique file name

    >>> code = "int f(i){return i*i;}"
    >>> _codeToFilename(code)[0:9]
    'dbf7e731_'
    >>> _codeToFilename(code)[9:-2].isdigit()
    True
    >>> _codeToFilename(code)[-2:]
    '.C'
    '''
    code_enc = code if type(code) == bytes else code.encode('utf-8')
    fileNameBase = sha1(code_enc).hexdigest()[0:8]
    timestamp = datetime.now().strftime("%H%M%S%f")
    return fileNameBase + "_" + timestamp + ".C"

def _dumpToUniqueFile(code):
    '''Dump code to file whose name is unique

    >>> code = "int f(i){return i*i;}"
    >>> _dumpToUniqueFile(code)[0:9]
    'dbf7e731_'
    >>> _dumpToUniqueFile(code)[9:-2].isdigit()
    True
    >>> _dumpToUniqueFile(code)[-2:]
    '.C'
    '''
    fileName = _codeToFilename(code)
    with open (fileName,'w') as ofile:
      code_dec = code if type(code) != bytes else code.decode('utf-8')
      ofile.write(code_dec)
    return fileName

def isPlatformApple():
   return _getPlatform() == 'darwin';

def invokeAclic(cell):
    fileName = _dumpToUniqueFile(cell)
    if isPlatformApple():
        _invokeAclicMac(fileName)
    else:
        processCppCode(".L %s+" %fileName)

transformers = []

class StreamCapture(object):
    def __init__(self, ip=get_ipython()):
        # For the registration
        self.shell = ip

        self.ioHandler = handlers.IOHandler()
        self.flag = True
        self.outString = ""
        self.errString = ""

        self.poller = handlers.Poller()
        self.poller.start()
        self.asyncCapturer = handlers.Runner(self.syncCapture, self.poller)

        self.isFirstPreExecute = True
        self.isFirstPostExecute = True

    def syncCapture(self, defout = ''):
        self.outString = defout
        self.errString = defout
        waitTimes = [.01, .01, .02, .04, .06, .08, .1]
        lenWaitTimes = 7

        iterIndex = 0
        while self.flag:
            self.ioHandler.Poll()
            if not self.flag: return
            waitTime = .1 if iterIndex >= lenWaitTimes else waitTimes[iterIndex]
            time.sleep(waitTime)

    def pre_execute(self):
        if self.isFirstPreExecute:
            self.isFirstPreExecute = False
            return 0

        self.flag = True
        self.ioHandler.Clear()
        self.ioHandler.InitCapture()
        self.asyncCapturer.AsyncRun('')

    def post_execute(self):
        if self.isFirstPostExecute:
            self.isFirstPostExecute = False
            self.isFirstPreExecute = False
            return 0
        self.flag = False
        self.asyncCapturer.Wait()
        self.ioHandler.Poll()
        self.ioHandler.EndCapture()

        # Print for the notebook
        out = self.ioHandler.GetStdout()
        err = self.ioHandler.GetStderr()
        if not transformers:
            sys.stdout.write(out)
            sys.stderr.write(err)
        else:
            for t in transformers:
                (out, err, otype) = t(out, err)
                if otype == 'html':
                    IPython.display.display(HTML(out))
                    IPython.display.display(HTML(err))
        return 0

    def register(self):
        self.shell.events.register('pre_execute', self.pre_execute)
        self.shell.events.register('post_execute', self.post_execute)

    def __del__(self):
        self.poller.Stop()

def setStyle():
    style=ROOT.gStyle
    style.SetFuncWidth(2)

captures = []

def loadMagicsAndCapturers():
    global captures
    extNames = ["JupyROOT.magics." + name for name in ["cppmagic","jsrootmagic"]]
    ip = get_ipython()
    extMgr = ExtensionManager(ip)
    for extName in extNames:
        extMgr.load_extension(extName)
    captures.append(StreamCapture())
    captures.append(canvas.CaptureDrawnPrimitives())

    for capture in captures: capture.register()

def declareProcessLineWrapper():
    ROOT.gInterpreter.Declare("""
TInterpreter::EErrorCode ProcessLineWrapper(const char* line) {
    TInterpreter::EErrorCode err;
    gInterpreter->ProcessLine(line, &err);
    return err;
}
""")

def enhanceROOTModule():
    ROOT.enableJSVis = interactive.enableJSVis
    ROOT.disableJSVis = interactive.disableJSVis
    ROOT.enableJSVisDebug = interactive.enableJSVisDebug
    ROOT.disableJSVisDebug = interactive.disableJSVisDebug

def enableCppHighlighting():
    ipDispJs = IPython.display.display_javascript
    # Define highlight mode for %%cpp magic
    ipDispJs(_jsMagicHighlight.format(cppMIME = cppMIME), raw=True)

def iPythonize():
    setStyle()
    loadMagicsAndCapturers()
    declareProcessLineWrapper()
    #enableCppHighlighting()
    enhanceROOTModule()
    welcomeMsg()

