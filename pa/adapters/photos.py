"""Photo search (read-only, MediaStore) and opening one photo in the system viewer.
Permission: READ_MEDIA_IMAGES on Android 13+, READ_EXTERNAL_STORAGE on 10-12.
Android 14+ may grant only user-selected photos ('partial')."""
from . import android_util as au
from .base import Adapter, Result


class AndroidPhotosAdapter(Adapter):
    name = "photos"

    def capability_check(self):
        return au.ANDROID

    def permission_check(self):
        sdk = au.sdk_int()
        if sdk >= 33:
            if au.granted(au.READ_MEDIA_IMAGES):
                return "granted"
            if sdk >= 34 and au.granted(au.READ_MEDIA_VISUAL_USER_SELECTED):
                return "partial"
            return "denied"
        return "granted" if au.granted(au.READ_EXTERNAL_STORAGE) else "denied"

    def required_permissions(self):
        sdk = au.sdk_int()
        if sdk >= 34:
            return [au.READ_MEDIA_IMAGES, au.READ_MEDIA_VISUAL_USER_SELECTED]
        if sdk >= 33:
            return [au.READ_MEDIA_IMAGES]
        return [au.READ_EXTERNAL_STORAGE]

    def _uri(self):
        return au.autoclass("android.provider.MediaStore$Images$Media").EXTERNAL_CONTENT_URI

    def search(self, start_ms, end_ms, keyword=None, limit=6):
        """{count, items:[{id, name, taken_ms, album}]} newest first."""
        sel = "datetaken >= ? AND datetaken < ?"
        args = [str(int(start_ms)), str(int(end_ms))]
        if keyword:
            sel += " AND (_display_name LIKE ? OR bucket_display_name LIKE ?)"
            args += ["%" + keyword + "%", "%" + keyword + "%"]
        cur = au.mActivity.getContentResolver().query(
            self._uri(), ["_id", "_display_name", "datetaken", "bucket_display_name"],
            sel, args, "datetaken DESC")
        count = cur.getCount() if cur is not None else 0
        items = [{"id": int(r[0]), "name": r[1] or "", "taken_ms": int(r[2] or 0), "album": r[3] or ""}
                 for r in au.rows(cur, 4, limit=limit)]
        return {"count": count, "items": items}

    def open(self, photo_id):
        try:
            Intent = au.autoclass("android.content.Intent")
            ContentUris = au.autoclass("android.content.ContentUris")
            it = Intent(Intent.ACTION_VIEW)
            it.setDataAndType(ContentUris.withAppendedId(self._uri(), int(photo_id)), "image/*")
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            au.mActivity.startActivity(it)
            return Result("handed_off", "photo opened in system viewer")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return Result("failed", "could not open photo: %s" % type(ex).__name__)
