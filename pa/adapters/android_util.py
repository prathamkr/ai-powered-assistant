"""Small Android helpers shared by adapters. Safe to import on desktop (ANDROID=False)."""
try:
    from jnius import autoclass  # type: ignore
    from android import mActivity  # type: ignore
    ANDROID = True
except Exception:
    autoclass = None
    mActivity = None
    ANDROID = False

READ_CONTACTS = "android.permission.READ_CONTACTS"
CALL_PHONE = "android.permission.CALL_PHONE"
READ_PHONE_STATE = "android.permission.READ_PHONE_STATE"
READ_MEDIA_IMAGES = "android.permission.READ_MEDIA_IMAGES"
READ_MEDIA_VISUAL_USER_SELECTED = "android.permission.READ_MEDIA_VISUAL_USER_SELECTED"
READ_EXTERNAL_STORAGE = "android.permission.READ_EXTERNAL_STORAGE"
RECORD_AUDIO = "android.permission.RECORD_AUDIO"


def granted(perm):
    if not ANDROID:
        return False
    # Context.checkSelfPermission is a plain framework call: reliable from any thread
    # (on the phone the android.permissions helper once reported a granted permission as missing).
    try:
        return int(mActivity.checkSelfPermission(perm)) == 0  # PackageManager.PERMISSION_GRANTED
    except Exception:
        try:
            from android.permissions import check_permission  # type: ignore
            return bool(check_permission(perm))
        except Exception:
            return False


def sdk_int():
    if not ANDROID:
        return 0
    return int(autoclass("android.os.Build$VERSION").SDK_INT)


def rows(cursor, n_cols, limit=None):
    """Read a ContentResolver cursor into Python lists and always close it."""
    out = []
    if cursor is None:
        return out
    try:
        while cursor.moveToNext():
            out.append([cursor.getString(i) for i in range(n_cols)])
            if limit and len(out) >= limit:
                break
    finally:
        cursor.close()
    return out
