"""Private Windows state using protected user ACLs and reparse-point rejection."""
import ctypes
import os
from pathlib import Path


def reject_reparse(path):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetFileAttributesW.argtypes = [w.LPCWSTR]
    kernel.GetFileAttributesW.restype = w.DWORD
    for item in [Path(path), *Path(path).parents]:
        flags = kernel.GetFileAttributesW(str(item))
        if flags == 0xffffffff:
            if ctypes.get_last_error() not in (2, 3):
                raise OSError('Windows state path could not be inspected')
        elif flags & 0x400:
            raise ValueError('Windows state paths must not contain reparse points')


def _apis():
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    declarations = [
        (kernel, 'GetCurrentProcess', [], w.HANDLE),
        (kernel, 'CloseHandle', [w.HANDLE], w.BOOL),
        (kernel, 'LocalFree', [ctypes.c_void_p], ctypes.c_void_p),
        (security, 'OpenProcessToken', [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
        (security, 'GetTokenInformation', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
        (security, 'ConvertSidToStringSidW', [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)], w.BOOL),
        (security, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p], w.BOOL),
        (security, 'GetSecurityDescriptorDacl', [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)], w.BOOL),
        (security, 'SetNamedSecurityInfoW', [w.LPWSTR, ctypes.c_int, w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], w.DWORD),
        (security, 'GetNamedSecurityInfoW', [w.LPCWSTR, ctypes.c_int, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)], w.DWORD),
        (security, 'EqualSid', [ctypes.c_void_p, ctypes.c_void_p], w.BOOL),
    ]
    for library, name, args, result in declarations:
        fn = getattr(library, name); fn.argtypes = args; fn.restype = result
    return kernel, security


def _token_identity(security, token, information_class):
    from ctypes import wintypes as w
    length = w.DWORD()
    security.GetTokenInformation(token, information_class, None, 0, ctypes.byref(length))
    if not length.value or length.value > 65536:
        raise OSError('Windows token identity size unavailable')
    buffer = ctypes.create_string_buffer(length.value)
    if not security.GetTokenInformation(token, information_class, buffer, length, ctypes.byref(length)):
        raise OSError('Windows token identity unavailable')
    return buffer, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]


def protect(path):
    from ctypes import wintypes as w
    reject_reparse(path)
    kernel, security = _apis()
    token = w.HANDLE()
    descriptor = ctypes.c_void_p(); old = ctypes.c_void_p(); sid_text = w.LPWSTR()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError('Windows user token unavailable')
        user_buffer, sid = _token_identity(security, token, 1)
        owner_buffer, default_owner = _token_identity(security, token, 4)
        owner = ctypes.c_void_p()
        if security.GetNamedSecurityInfoW(str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(old)):
            raise OSError('Windows private state ownership unavailable')
        user_owned = bool(security.EqualSid(sid, owner))
        if not user_owned and not security.EqualSid(default_owner, owner):
            raise OSError('Windows private state must belong to the current user or token default owner')
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError('Windows private ACL identity unavailable')
        sddl = 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;' + sid_text.value + ')'
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError('Windows private ACL creation failed')
        present = w.BOOL(); defaulted = w.BOOL(); dacl = ctypes.c_void_p()
        if not security.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present:
            raise OSError('Windows private ACL unavailable')
        # Elevated tokens can create files with their verified default group owner.
        owner_flag, new_owner = (0, None) if user_owned else (1, sid)
        if security.SetNamedSecurityInfoW(str(path), 1, 4 | 0x80000000 | owner_flag, new_owner, None, dacl, None):
            raise OSError('Windows private ACL application failed')
        reject_reparse(path)
    finally:
        if token: kernel.CloseHandle(token)
        for value in (descriptor, old, ctypes.cast(sid_text, ctypes.c_void_p)):
            if value: kernel.LocalFree(value)


def prepare_private_file(path):
    from ctypes import wintypes as w
    path = Path(path).absolute()
    reject_reparse(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    protect(path.parent)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000 | 0x40000000, 3, None, 4, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError('Windows private state file could not be opened')
    try:
        class AttributeTag(ctypes.Structure):
            _fields_ = [('attributes', w.DWORD), ('tag', w.DWORD)]
        kernel.GetFileInformationByHandleEx.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.GetFileInformationByHandleEx.restype = w.BOOL
        info = AttributeTag()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or info.attributes & 0x400:
            raise OSError('Windows state handle must reference a regular file')
        reject_reparse(path)
        protect(path)
    finally:
        kernel.CloseHandle(handle)
