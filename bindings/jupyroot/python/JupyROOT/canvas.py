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

import fnmatch
import sys
import tempfile
import time
from contextlib import contextmanager

import IPython.display
import ROOT
from IPython import get_ipython
from IPython.display import HTML

# We want iPython to take over the graphics
ROOT.gROOT.SetBatch()

@contextmanager
def _setIgnoreLevel(level):
    originalLevel = ROOT.gErrorIgnoreLevel
    ROOT.gErrorIgnoreLevel = level
    yield
    ROOT.gErrorIgnoreLevel = originalLevel

_jsNotDrawableClassesPatterns = ["TEve*","TF3","TPolyLine3D"]

_jsCanvasWidth = 800
_jsCanvasHeight = 600
_jsCode = """

<div id="{jsDivId}"
     style="width: {jsCanvasWidth}px; height: {jsCanvasHeight}px">
</div>
<script>
if (typeof require !== 'undefined') {{

    // We are in jupyter notebooks, use require.js which should be configured already
    require(['scripts/JSRoot.core'],
        function(Core) {{
           display_{jsDivId}(Core);
        }}
    );

}} else if (typeof JSROOT !== 'undefined') {{

   // JSROOT already loaded, just use it
   display_{jsDivId}(JSROOT);

}} else {{

    // We are in jupyterlab without require.js, directly loading jsroot
    // Jupyterlab might be installed in a different base_url so we need to know it.
    try {{
        var base_url = JSON.parse(document.getElementById('jupyter-config-data').innerHTML).baseUrl;
    }} catch(_) {{
        var base_url = '/';
    }}

    // Try loading a local version of requirejs and fallback to cdn if not possible.
    script_load(base_url + 'static/scripts/JSRoot.core.js', script_success, function(){{
        console.error('Fail to load JSROOT locally, please check your jupyter_notebook_config.py file')
        script_load('https://root.cern/js/6.1.0/scripts/JSRoot.core.min.js', script_success, function(){{
            document.getElementById("{jsDivId}").innerHTML = "Failed to load JSROOT";
        }});
    }});
}}

function script_load(src, on_load, on_error) {{
    var script = document.createElement('script');
    script.src = src;
    script.onload = on_load;
    script.onerror = on_error;
    document.head.appendChild(script);
}}

function script_success() {{
   display_{jsDivId}(JSROOT);
}}

function display_{jsDivId}(Core) {{
   var obj = Core.parse({jsonContent});
   Core.settings.HandleKeys = false;
   Core.draw("{jsDivId}", obj, "{jsDrawOptions}");
}}
</script>
"""

TBufferJSONErrorMessage="The TBufferJSON class is necessary for JS visualisation to work and cannot be found. Did you enable the http module (-D http=ON for CMake)?"

def TBufferJSONAvailable():
   if hasattr(ROOT,"TBufferJSON"):
       return True
   print(TBufferJSONErrorMessage, file=sys.stderr)
   return False

_enableJSVis = False
_enableJSVisDebug = False
def enableJSVis():
    if not TBufferJSONAvailable():
       return
    global _enableJSVis
    _enableJSVis = True

def disableJSVis():
    global _enableJSVis
    _enableJSVis = False

def enableJSVisDebug():
    if not TBufferJSONAvailable():
       return
    global _enableJSVis
    global _enableJSVisDebug
    _enableJSVis = True
    _enableJSVisDebug = True

def disableJSVisDebug():
    global _enableJSVis
    global _enableJSVisDebug
    _enableJSVis = False
    _enableJSVisDebug = False

def ProduceCanvasJson(canvas):
   # Add extra primitives to canvas with custom colors, palette, gStyle
   prim = canvas.GetListOfPrimitives()

   style = ROOT.gStyle
   colors = ROOT.gROOT.GetListOfColors()
   palette = None

   # always provide gStyle object
   if prim.FindObject(style):
      style = None
   else:
      prim.Add(style)

   cnt = 0
   for n in range(colors.GetLast()+1):
      if colors.At(n):
          cnt = cnt+1

   # add all colors if there are more than 598 colors defined
   if cnt < 599 or prim.FindObject(colors):
      colors = None
   else:
      prim.Add(colors)

   if colors:
      pal = ROOT.TColor.GetPalette()
      palette = ROOT.TObjArray()
      palette.SetName("CurrentColorPalette")
      for i in range(pal.GetSize()):
         palette.Add(colors.At(pal[i]))
      prim.Add(palette)

   ROOT.TColor.DefinedColors()

   canvas_json = ROOT.TBufferJSON.ConvertToJSON(canvas, 3)

   # Cleanup primitives after conversion
   if style is not None:
       prim.Remove(style)
   if colors is not None:
       prim.Remove(colors)
   if palette is not None:
       prim.Remove(palette)

   return canvas_json

def GetCanvasDrawers():
    lOfC = ROOT.gROOT.GetListOfCanvases()
    return [NotebookDrawer(can) for can in lOfC if can.IsDrawn()]

def GetGeometryDrawer():
    if not hasattr(ROOT, 'gGeoManager'):
        return
    if not ROOT.gGeoManager:
        return
    if not ROOT.gGeoManager.GetUserPaintVolume():
        return
    vol = ROOT.gGeoManager.GetTopVolume()
    if vol:
        return NotebookDrawer(vol)

def GetDrawers():
    drawers = GetCanvasDrawers()
    geometryDrawer = GetGeometryDrawer()
    if geometryDrawer:
        drawers.append(geometryDrawer)
    return drawers

def DrawGeometry():
    drawer = GetGeometryDrawer()
    if drawer:
        drawer.Draw()

def DrawCanvases():
    drawers = GetCanvasDrawers()
    for drawer in drawers:
        drawer.Draw()

def NotebookDraw():
    DrawGeometry()
    DrawCanvases()

class CaptureDrawnPrimitives(object):
    '''
    Capture the canvas which is drawn to display it.
    '''
    def __init__(self, ip=get_ipython()):
        self.shell = ip

    def _post_execute(self):
        NotebookDraw()

    def register(self):
        self.shell.events.register('post_execute', self._post_execute)

class NotebookDrawer(object):
    '''
    Capture the canvas which is drawn and decide if it should be displayed using
    jsROOT.
    '''

    def __init__(self, theObject):
        self.drawableObject = theObject
        self.isCanvas = self.drawableObject.ClassName() == "TCanvas"

    def __del__(self):
       if self.isCanvas:
           self.drawableObject.ResetDrawn()
       else:
           ROOT.gGeoManager.SetUserPaintVolume(None)

    def _getListOfPrimitivesNamesAndTypes(self):
       """
       Get the list of primitives in the pad, recursively descending into
       histograms and graphs looking for fitted functions.
       """
       primitives = self.drawableObject.GetListOfPrimitives()
       primitivesNames = map(lambda p: p.ClassName(), primitives)
       return sorted(primitivesNames)

    def _getUID(self):
        '''
        Every DIV containing a JavaScript snippet must be unique in the
        notebook. This method provides a unique identifier.
        With the introduction of JupyterLab, multiple Notebooks can exist
        simultaneously on the same HTML page. In order to ensure a unique
        identifier with the UID throughout all open Notebooks the UID is
        generated as a timestamp.
        '''
        return int(round(time.time() * 1000))

    def _canJsDisplay(self):
        if not TBufferJSONAvailable():
           return False
        if not self.isCanvas:
            return True
        # to be optimised
        if not _enableJSVis:
            return False
        primitivesTypesNames = self._getListOfPrimitivesNamesAndTypes()
        for unsupportedPattern in _jsNotDrawableClassesPatterns:
            for primitiveTypeName in primitivesTypesNames:
                if fnmatch.fnmatch(primitiveTypeName,unsupportedPattern):
                    print("The canvas contains an object of a type jsROOT cannot currently handle (%s). Falling back to a static png." %primitiveTypeName, file=sys.stderr)
                    return False
        return True

    def _getJsCode(self):
        # produce JSON for the canvas
        json = ProduceCanvasJson(self.drawableObject)

        # Here we could optimise the string manipulation
        divId = 'root_plot_' + str(self._getUID())

        height = _jsCanvasHeight
        width = _jsCanvasHeight
        options = "all"

        if self.isCanvas:
            height = self.drawableObject.GetWw()
            width = self.drawableObject.GetWh()
            options = ""

        thisJsCode = _jsCode.format(jsCanvasWidth = height,
                                    jsCanvasHeight = width,
                                    jsonContent = json.Data(),
                                    jsDrawOptions = options,
                                    jsDivId = divId)
        return thisJsCode

    def _getJsDiv(self):
        return HTML(self._getJsCode())

    def _jsDisplay(self):
        IPython.display.display(self._getJsDiv())
        return 0

    def _getPngImage(self):
        ofile = tempfile.NamedTemporaryFile(suffix=".png")
        with _setIgnoreLevel(ROOT.kError):
            self.drawableObject.SaveAs(ofile.name)
        img = IPython.display.Image(filename=ofile.name, format='png', embed=True)
        return img

    def _pngDisplay(self):
        img = self._getPngImage()
        IPython.display.display(img)

    def _display(self):
       if _enableJSVisDebug:
          self._pngDisplay()
          self._jsDisplay()
       else:
         if self._canJsDisplay():
            self._jsDisplay()
         else:
            self._pngDisplay()

    def GetDrawableObjects(self):
        if not self.isCanvas:
           return [self._getJsDiv()]

        if _enableJSVisDebug:
           return [self._getJsDiv(), self._getPngImage()]

        if self._canJsDisplay():
           return [self._getJsDiv()]
        else:
           return [self._getPngImage()]

    def Draw(self):
        self._display()
        return 0