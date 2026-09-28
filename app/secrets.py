"""Windows user-scoped DPAPI protection. Never fall back to plaintext storage."""
import base64
import ctypes
import os
from ctypes import wintypes

class SecretError(ValueError):
    pass

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def transform(data, decrypt=False):
    if os.name!='nt':
        raise SecretError('Secure phone-key storage requires Windows in this build.')
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    try:
        # UI forbidden, current user scope; never CRYPTPROTECT_LOCAL_MACHINE.
        if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
            raise SecretError('Windows could not unlock the phone key. Reconnect it in Settings using this Windows account.')
        return ctypes.string_at(target.data,target.size)
    finally:
        ctypes.memset(buffer,0,len(buffer))
        if target.data:
            ctypes.memset(target.data,0,target.size)
            kernel.LocalFree(target.data)

def protect(value):
    return {'protection':'windows-dpapi-v1','ciphertext':base64.b64encode(transform(value.encode('utf-8'))).decode('ascii')}

def unprotect(value):
    try:
        if not isinstance(value,dict) or value.get('protection')!='windows-dpapi-v1':raise ValueError()
        return transform(base64.b64decode(value['ciphertext'],validate=True),True).decode('utf-8')
    except (ValueError,KeyError,TypeError):
        raise SecretError('Phone key could not be read. Reconnect it in Settings.') from None
