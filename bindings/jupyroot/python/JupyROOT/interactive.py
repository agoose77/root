#!/usr/bin/env python
# -*- coding:utf-8 -*-
# -----------------------------------------------------------------------------
#  Authors: Omar Zapata <Omar.Zapata@cern.ch> http://oproject.org
#           Danilo Piparo <Danilo.Piparo@cern.ch> CERN
#           Enric Tejedor <enric.tejedor.saavedra@cern.ch> CERN
# -----------------------------------------------------------------------------

################################################################################
# Copyright (C) 1995-2020, Rene Brun and Fons Rademakers.                      #
# All rights reserved.                                                         #
#                                                                              #
# For the licensing terms see $ROOTSYS/LICENSE.                                #
# For the list of contributors see $ROOTSYS/README/CREDITS.                    #
################################################################################

import sys

import ROOT

TBufferJSONErrorMessage = "The TBufferJSON class is necessary for JS visualisation " \
                          "to work and cannot be found. Did you enable the http " \
                          "module (-D http=ON for CMake)?"


def IsTBufferJSONAvailable():
    if hasattr(ROOT, "TBufferJSON"):
        return True
    print(TBufferJSONErrorMessage, file=sys.stderr)
    return False


_enableJSVis = False
_enableJSVisDebug = False


def enableJSVis():
    if not IsTBufferJSONAvailable():
        return
    global _enableJSVis
    _enableJSVis = True


def disableJSVis():
    global _enableJSVis
    _enableJSVis = False


def enableJSVisDebug():
    if not IsTBufferJSONAvailable():
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
