import bpy, os, sys, importlib
bpy.ops.preferences.addon_enable(module='bl_ext.user_default.mpfb')
def imp(mod, key):
    return getattr(importlib.import_module('bl_ext.user_default.mpfb.' + mod), key)
HumanService = imp('services.humanservice', 'HumanService')
TargetService = imp('services.targetservice', 'TargetService')
HOP = imp('entities.objectproperties', 'HumanObjectProperties')
