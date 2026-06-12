# Patches

## websocket-client 1.x compatibility fix for roonapi 0.1.6

`roonapi` 0.1.6 was written against `websocket-client < 1.0`, which changed its
callback signature in v1.0. If you see errors like:

```
AttributeError: 'WebSocketApp' object has no attribute 'split'
```

apply this patch to the installed library file (find it with
`pip show roonapi` → Location):

**File:** `roonapi/roonapisocket.py`

```diff
-    def on_message(self, w_socket, message=None):
-        if not message:
-            message = w_socket
-        try:
-            message = message.decode("utf-8")
+    def on_message(self, w_socket, message=None):
+        if message is None:
+            message = w_socket
+        try:
+            if isinstance(message, bytes):
+                message = message.decode("utf-8")
```

```diff
-    def on_error(self, w_socket, error=None):
-        if not error:
-            error = w_socket
+    def on_error(self, w_socket, error=None):
+        if error is None:
+            error = w_socket
```

After editing, delete any `.pyc` bytecode cache for the file:

```bash
find $(python3 -c "import roonapi; import os; print(os.path.dirname(roonapi.__file__))") \
  -name "roonapisocket*.pyc" -delete
```
