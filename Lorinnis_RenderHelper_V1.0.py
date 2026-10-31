bl_info = {
    "name": "渲染助手 RenderHelper (渲染队列)",
    "author": "RenderHelper",
    "version": (0, 0, 4),   #0.0.4：开始渲染前先清理队列目录内的旧 BAT 脚本，只保留最新一个
    "blender": (2, 93, 0),   #已测试5.2.1LTS和3.6.5
    "location": "3D 视图 > 侧边栏(N) > 渲染助手",
    "description": "管理用户指定目录下的渲染队列；一键生成并执行批量渲染 BAT（可选完成后关机）。",
    "category": "Render",
    "support": "COMMUNITY",
}

#此插件由络离/络琳尼丝开发

import bpy
import os
import datetime

from bpy.props import (
    StringProperty,
    BoolProperty,
    PointerProperty,
)
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup


QUEUE_SUBDIR = "RenderQueue"
BAT_NAME = "render_queue.bat"
BAT_EXT = ".bat"


_ADDON_ID = "" if __name__ == "__main__" else __name__


def human_size(size):
    try:
        size = float(size)
    except Exception:
        return "?"
    if size >= 1024 * 1024:
        return "%.1f MB" % (size / 1048576.0)
    if size >= 1024:
        return "%.1f KB" % (size / 1024.0)
    return "%d B" % int(size)


def get_prefs():
    if not _ADDON_ID:
        return None
    try:
        addon = bpy.context.preferences.addons.get(_ADDON_ID)
    except Exception:
        return None
    if addon is None:
        return None
    return getattr(addon, "preferences", None)


def get_queue_dir_setting():
    p = get_prefs()
    if p is not None:
        try:
            return (p.queue_dir or "").strip()
        except Exception:
            return ""
    scene = getattr(bpy.context, "scene", None)
    s = getattr(scene, "rta", None) if scene is not None else None
    if s is None:
        return ""
    try:
        return (s.queue_dir or "").strip()
    except Exception:
        return ""


def set_queue_dir_setting(value):
    p = get_prefs()
    if p is not None:
        try:
            p.queue_dir = value
            return True
        except Exception:
            pass
    scene = getattr(bpy.context, "scene", None)
    s = getattr(scene, "rta", None) if scene is not None else None
    if s is None:
        return False
    try:
        s.queue_dir = value
        return True
    except Exception:
        return False


def current_blend_path():
    return bpy.data.filepath or ""


def get_queue_dir():
    custom = get_queue_dir_setting()
    if custom:
        return bpy.path.abspath(custom)

    path = current_blend_path()
    if not path:
        return ""
    folder = os.path.dirname(os.path.abspath(path))
    if not folder:
        return ""
    if os.path.basename(folder).lower() == QUEUE_SUBDIR.lower():
        return folder
    return os.path.join(folder, QUEUE_SUBDIR)


def ensure_queue_dir(queue_dir):
    if not queue_dir:
        return "", "尚未指定渲染队列目录，请先点击「指定队列目录」"
    try:
        os.makedirs(queue_dir, exist_ok=True)
    except Exception as exc:
        return "", "创建队列目录失败：%s" % exc
    if not os.path.isdir(queue_dir):
        return "", "队列目录不可用：%s" % queue_dir
    return queue_dir, ""


def list_blend_files(queue_dir, limit=20):
    items = []
    if not queue_dir or not os.path.isdir(queue_dir):
        return items
    entries = []
    try:
        for name in os.listdir(queue_dir):
            if not name.lower().endswith(".blend"):
                continue
            full = os.path.join(queue_dir, name)
            if not os.path.isfile(full):
                continue
            try:
                entries.append((os.path.getmtime(full), name, os.path.getsize(full)))
            except Exception:
                entries.append((0.0, name, 0))
    except Exception:
        return items
    entries.sort(key=lambda item: item[0], reverse=True)
    for _mtime, name, size in entries[:limit]:
        items.append((name, human_size(size)))
    return items


def queue_current_entry(scene):
    s = getattr(scene, "rta", None)
    queue_dir = get_queue_dir()
    if s is None or not queue_dir or not os.path.isdir(queue_dir):
        return ""
    candidates = [s.queue_current]
    if bpy.data.filepath:
        candidates.append(os.path.basename(bpy.data.filepath))
    if s.last_saved_path:
        candidates.append(os.path.basename(s.last_saved_path))
    for name in candidates:
        if name and os.path.isfile(os.path.join(queue_dir, name)):
            return name
    return ""


def guard_blend_target(queue_dir, filename):
    if not filename or not filename.lower().endswith(".blend"):
        return "", "只能操作 .blend 文件"
    if os.path.basename(filename) != filename:
        return "", "非法文件名"
    if not queue_dir or not os.path.isdir(queue_dir):
        return "", "队列目录不可用"
    target = os.path.abspath(os.path.join(queue_dir, filename))
    if os.path.normcase(os.path.dirname(target)) != os.path.normcase(os.path.abspath(queue_dir)):
        return "", "目标不在队列目录内"
    if not os.path.isfile(target):
        return "", "文件不存在：%s" % filename
    current = bpy.data.filepath
    if current and os.path.normcase(os.path.abspath(current)) == os.path.normcase(target):
        return "", "该文件正是当前正在编辑的工程，已跳过"
    return target, ""


def queue_bat_path(queue_dir):
    if not queue_dir:
        return ""
    return os.path.join(queue_dir, BAT_NAME)


def list_bat_files(queue_dir):
    """列出队列目录（脚本所在目录）第一层的所有 .bat 脚本，不递归子目录。"""
    items = []
    if not queue_dir or not os.path.isdir(queue_dir):
        return items
    try:
        names = os.listdir(queue_dir)
    except Exception:
        return items
    for name in names:
        if not name.lower().endswith(BAT_EXT):
            continue
        full = os.path.join(queue_dir, name)
        if os.path.isfile(full):
            items.append(full)
    items.sort(key=lambda p: p.lower())
    return items


def purge_bat_files(queue_dir, exclude=()):
    """删除队列目录下所有旧 .bat 脚本。

    返回 (已删除的文件名列表, 删除失败的文件名列表)。
    删除失败的通常是正在被 cmd.exe 占用的脚本，此时保留原文件、不中断流程。
    """
    deleted, failed = [], []
    if not queue_dir or not os.path.isdir(queue_dir):
        return deleted, failed
    skip = set()
    for path in exclude or ():
        if path:
            skip.add(os.path.normcase(os.path.abspath(path)))
    for full in list_bat_files(queue_dir):
        if os.path.normcase(os.path.abspath(full)) in skip:
            continue
        name = os.path.basename(full)
        try:
            os.remove(full)
            deleted.append(name)
        except Exception:
            failed.append(name)
    return deleted, failed


def purge_note(removed, busy):
    """把清理结果拼成一句提示前缀，无内容时返回空串。"""
    parts = []
    if removed:
        parts.append("已清理 %d 个旧脚本" % len(removed))
    if busy:
        parts.append("%d 个旧脚本被占用未删除" % len(busy))
    if not parts:
        return ""
    return "，".join(parts) + "；"


def blender_executable():
    exe = ""
    try:
        exe = bpy.app.binary_path or ""
    except Exception:
        exe = ""
    return exe or "blender.exe"


def _bat_text(blender_exe, shutdown_after):
    text = (
        "@echo off\r\n"
        "chcp 936 >nul\r\n"
        'cd /d "%~dp0"\r\n'
        'for %%a in ("*.blend") do (\r\n'
        '"__BLENDER__" -b "%%a" -a\r\n'
        ")\r\n"
    )
    text = text.replace("__BLENDER__", blender_exe)
    if shutdown_after:
        text += (
            "echo 60 秒后关机，按任意键取消...\r\n"
            "shutdown /s /f /t 60\r\n"
            "timeout /t 60 >nul\r\n"
            "shutdown /a\r\n"
        )
    return text


def _encode_bat(text):
    for enc in ("gbk", "cp936", "mbcs", "utf-8"):
        try:
            return text.encode(enc)
        except Exception:
            continue
    return text.encode("utf-8", "replace")


def write_queue_bat(queue_dir, shutdown_after):
    if not queue_dir:
        return "", "尚未指定渲染队列目录"
    path = queue_bat_path(queue_dir)
    data = _encode_bat(_bat_text(blender_executable(), bool(shutdown_after)))
    try:
        with open(path, "wb") as fp:
            fp.write(data)
    except Exception as exc:
        return "", "写入脚本失败：%s" % exc
    return path, ""


def _on_shutdown_toggle(self, context):
    try:
        queue_dir = get_queue_dir()
        path = queue_bat_path(queue_dir)
        if not path or not os.path.isfile(path):
            return
        write_queue_bat(queue_dir, self.shutdown_after)
    except Exception:
        pass


class RTA_AddonPreferences(AddonPreferences):
    bl_idname = _ADDON_ID or "rta_preferences"

    queue_dir: StringProperty(
        name="渲染队列目录",
        subtype='DIR_PATH',
        default="",
        description="加入渲染队列的 .blend 副本存放位置；留空则回退为「工程目录/RenderQueue」")


class RTA_Properties(PropertyGroup):
    queue_dir: StringProperty(
        name="队列目录", subtype='DIR_PATH', default="",
        description="队列目录（仅在插件偏好设置不可用时使用，例如从文本编辑器直接运行）")
    blend_filename: StringProperty(
        name="队列文件名", default="",
        description="加入队列时使用的文件名；留空则用当前工程的文件名；工程未保存且留空则为 untitled")
    last_saved_path: StringProperty(name="最近加入", default="")
    last_saved_time: StringProperty(name="加入时间", default="")
    queue_current: StringProperty(
        name="队列当前工程", default="",
        description="渲染队列中代表当前工程的 .blend 文件名，「删除其它工程」时会保留它")

    shutdown_after: BoolProperty(
        name="完成后关机", default=False,
        description="勾选后，在 BAT 末尾追加关机指令：60 秒倒计时，命令行里按任意键取消",
        update=_on_shutdown_toggle)


class RTA_OT_set_queue_dir(Operator):
    bl_idname = "rta.set_queue_dir"
    bl_label = "指定渲染队列目录"
    bl_description = ("弹窗选择一个文件夹，用于存放加入渲染队列的 .blend 副本"
                      "（清空该目录设置即回退为「工程目录/RenderQueue」）")

    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        current = get_queue_dir()
        if current and os.path.isdir(current):
            self.directory = current
        if bpy.app.background:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        raw = (self.directory or "").strip()
        if not raw:
            self.report({'WARNING'}, "未选择队列目录")
            return {'CANCELLED'}
        target = bpy.path.abspath(raw)
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as exc:
            self.report({'ERROR'}, "无法创建队列目录：%s" % exc)
            return {'CANCELLED'}
        if not os.path.isdir(target):
            self.report({'ERROR'}, "队列目录不可用：%s" % target)
            return {'CANCELLED'}
        if not set_queue_dir_setting(target):
            self.report({'ERROR'}, "无法写入该设置（插件偏好设置不可用）")
            return {'CANCELLED'}
        self.report({'INFO'}, "渲染队列目录已设为：%s" % target)
        return {'FINISHED'}


class RTA_OT_add_to_queue(Operator):
    bl_idname = "rta.add_to_queue"
    bl_label = "添加当前工程到渲染队列"
    bl_description = ("把当前 .blend 复制到「指定的队列目录」"
                      "（固定用工程名，同名直接覆盖；当前正在编辑的文件不受影响；"
                      "工程未保存时直接从内存写出副本）")

    def execute(self, context):
        scene = context.scene
        s = scene.rta

        queue_dir, err = ensure_queue_dir(get_queue_dir())
        if not queue_dir:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        source = current_blend_path()
        name = (s.blend_filename or "").strip()
        if not name and source:
            name = os.path.basename(source)
        if not name:
            name = "untitled.blend"
        name = bpy.path.clean_name(os.path.splitext(name)[0]) or "untitled"
        filename = "%s.blend" % name
        target = os.path.join(queue_dir, filename)

        if source and os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
            self.report({'WARNING'}, "队列目录就是工程所在目录且同名，副本会覆盖原工程，已取消（请改目录或改文件名）")
            return {'CANCELLED'}

        overwrote = os.path.isfile(target)
        try:
            result = bpy.ops.wm.save_as_mainfile(
                filepath=target,
                check_existing=False,
                copy=True,
                compress=False,
                relative_remap=bool(source),
            )
        except Exception as exc:
            self.report({'ERROR'}, "加入队列失败：%s" % exc)
            return {'CANCELLED'}
        if 'FINISHED' not in result:
            self.report({'ERROR'}, "加入队列被取消")
            return {'CANCELLED'}

        s.queue_current = filename
        s.last_saved_path = target
        s.last_saved_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not source:
            self.report({'INFO'}, "工程尚未保存，已从内存状态写出队列副本：%s" % target)
        elif overwrote:
            self.report({'INFO'}, "已覆盖队列副本：%s" % target)
        else:
            self.report({'INFO'}, "已加入渲染队列：%s" % target)
        return {'FINISHED'}


class RTA_OT_delete_queue_file(Operator):
    bl_idname = "rta.delete_queue_file"
    bl_label = "从渲染队列中删除该工程"
    bl_description = "删除队列目录下的这个 .blend 工程文件（会先弹窗确认）"

    filename: StringProperty(default="")

    def invoke(self, context, event):
        if not self.filename:
            self.report({'ERROR'}, "未指定要删除的文件")
            return {'CANCELLED'}
        if bpy.app.background:
            return self.execute(context)
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.rta
        queue_dir = get_queue_dir()
        target, err = guard_blend_target(queue_dir, self.filename)
        if err:
            self.report({'WARNING'}, "未删除：%s" % err)
            return {'CANCELLED'}
        try:
            os.remove(target)
        except Exception as exc:
            self.report({'ERROR'}, "删除失败：%s" % exc)
            return {'CANCELLED'}
        if s.queue_current == self.filename:
            s.queue_current = ""
        if s.last_saved_path and os.path.basename(s.last_saved_path) == self.filename:
            s.last_saved_path = ""
        self.report({'INFO'}, "已删除：%s" % self.filename)
        return {'FINISHED'}


class RTA_OT_delete_other_blends(Operator):
    bl_idname = "rta.delete_other_blends"
    bl_label = "删除渲染队列中的其它工程"
    bl_description = ("删除队列目录下除「当前工程」以外的所有 .blend 文件"
                      "（会先弹窗确认；正在编辑的文件永远不会被删除）")

    def invoke(self, context, event):
        if bpy.app.background:
            return self.execute(context)
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        queue_dir = get_queue_dir()
        if not queue_dir or not os.path.isdir(queue_dir):
            self.report({'ERROR'}, "队列目录不可用，请先保存工程并加入队列")
            return {'CANCELLED'}

        keep = queue_current_entry(scene)
        if not keep:
            self.report({'ERROR'}, "队列里没识别到当前工程，请先点「添加当前工程」再删除其它")
            return {'CANCELLED'}

        deleted, skipped = [], []
        for name, _size in list_blend_files(queue_dir, limit=1000):
            if name == keep:
                continue
            target, err = guard_blend_target(queue_dir, name)
            if err:
                skipped.append(name)
                continue
            try:
                os.remove(target)
                deleted.append(name)
            except Exception:
                skipped.append(name)

        if deleted:
            self.report({'INFO'}, "已删除 %d 个工程，保留：%s%s" % (
                len(deleted), keep, ("；跳过 %d 个" % len(skipped)) if skipped else ""))
            return {'FINISHED'}
        self.report({'WARNING'}, "没有可删除的工程（保留：%s）" % keep)
        return {'CANCELLED'}


class RTA_OT_start_render(Operator):
    bl_idname = "rta.start_render"
    bl_label = "开始渲染"
    bl_description = ("先删除队列目录下已存在的其它 BAT 脚本，再重新生成 render_queue.bat 并立即执行"
                      "（等同双击运行，会弹出命令行窗口逐个渲染）；"
                      "勾选「完成后关机」时渲染结束后自动关机")

    def execute(self, context):
        s = context.scene.rta

        queue_dir, err = ensure_queue_dir(get_queue_dir())
        if not queue_dir:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        # 第一步：清理脚本所在目录里残留的旧 BAT，确保每次渲染只保留当前最新的一个
        removed, busy = purge_bat_files(queue_dir)

        # 第二步：创建新的渲染脚本
        bat, err = write_queue_bat(queue_dir, s.shutdown_after)
        if not bat:
            existing = queue_bat_path(queue_dir)
            if existing and os.path.isfile(existing):
                bat = existing
                self.report({'WARNING'}, "脚本重写失败（可能上次渲染仍在运行），将直接执行现有脚本")
            else:
                self.report({'ERROR'}, "%s%s" % (
                    err,
                    ("；%d 个旧脚本无法删除（可能正在运行）：%s" % (len(busy), "、".join(busy))) if busy else ""))
                return {'CANCELLED'}

        count = len(list_blend_files(queue_dir, limit=10000))
        if not count:
            self.report({'WARNING'}, "%s队列目录里没有 .blend 工程，已取消（渲染脚本已生成）" % purge_note(removed, busy))
            return {'CANCELLED'}

        # 第三步：执行新脚本
        try:
            os.startfile(bat)
        except Exception:
            try:
                import subprocess
                subprocess.Popen(
                    ["cmd.exe", "/c", bat],
                    cwd=queue_dir,
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
                )
            except Exception as exc:
                self.report({'ERROR'}, "启动失败：%s" % exc)
                return {'CANCELLED'}

        prefix = purge_note(removed, busy)
        if s.shutdown_after:
            self.report({'INFO'}, "%s已生成并启动渲染（%d 个工程），完成后将关机" % (prefix, count))
        else:
            self.report({'INFO'}, "%s已生成并启动渲染（%d 个工程）" % (prefix, count))
        return {'FINISHED'}


class RTA_OT_clear_queue(Operator):
    bl_idname = "rta.clear_queue"
    bl_label = "清空队列与脚本"
    bl_description = ("删除队列目录下的 BAT 脚本与所有 .blend 文件（会先弹窗确认；"
                      "当前正在编辑的工程永远不会被删除）")

    def invoke(self, context, event):
        if bpy.app.background:
            return self.execute(context)
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        queue_dir = get_queue_dir()
        if not queue_dir or not os.path.isdir(queue_dir):
            self.report({'ERROR'}, "队列目录不可用，请先指定队列目录")
            return {'CANCELLED'}

        removed_blend, skipped = 0, 0
        for name, _size in list_blend_files(queue_dir, limit=10000):
            target, err = guard_blend_target(queue_dir, name)
            if err:
                skipped += 1
                continue
            try:
                os.remove(target)
                removed_blend += 1
            except Exception:
                skipped += 1

        removed_bat = False
        bat = queue_bat_path(queue_dir)
        if bat and os.path.isfile(bat):
            try:
                os.remove(bat)
                removed_bat = True
            except Exception:
                pass

        if not removed_blend and not removed_bat:
            self.report({'WARNING'}, "没有可清理的内容%s" % (
                "（跳过 %d 个）" % skipped if skipped else ""))
            return {'CANCELLED'}

        self.report({'INFO'}, "已清空：%d 个工程%s%s" % (
            removed_blend,
            "、1 个 BAT 脚本" if removed_bat else "",
            "；跳过 %d 个" % skipped if skipped else ""))
        return {'FINISHED'}


class RTA_PT_main(Panel):
    bl_idname = "RTA_PT_main"
    bl_label = "渲染助手 RenderHelper"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "渲染助手"

    def draw(self, context):
        layout = self.layout
        s = context.scene.rta

        queue_dir = get_queue_dir()
        blends = list_blend_files(queue_dir)
        total = len(list_blend_files(queue_dir, limit=10000))
        keep = queue_current_entry(context.scene)
        box = layout.box()
        box.label(text="渲染队列（%d 个工程）" % total, icon='FILE_BLEND')

        col = box.column(align=True)
        col.scale_y = 0.8
        prefs = get_prefs()
        if prefs is not None:
            col.prop(prefs, "queue_dir", text="目录")
        elif queue_dir:
            col.label(text=queue_dir, icon='FILE_FOLDER')
        else:
            col.label(text="未指定队列目录", icon='ERROR')
        if not queue_dir:
            col.label(text="请先指定队列目录，再添加工程", icon='INFO')

        col = box.column(align=True)
        col.scale_y = 0.9
        col.prop(s, "blend_filename", text="文件名")

        row = box.row(align=True)
        row.operator("rta.set_queue_dir", text="指定队列目录", icon='FILEBROWSER')

        row = box.row(align=True)
        row.operator("rta.add_to_queue", text="添加当前工程", icon='ADD')
        row.operator("rta.delete_other_blends", text="删除其它", icon='TRASH')

        col = box.column(align=True)
        col.scale_y = 0.85
        if blends:
            for name, size_text in blends:
                row = col.row(align=True)
                if name == keep:
                    row.label(text=name, icon='CHECKMARK')
                else:
                    row.label(text=name)
                row.label(text=size_text)
                op = row.operator("rta.delete_queue_file", text="", icon='X')
                op.filename = name
            if total > len(blends):
                col.label(text="仅显示最近 %d 个，另有 %d 个未显示" % (
                    len(blends), total - len(blends)), icon='INFO')
            if not keep:
                col.label(text="先点「添加当前工程」标记当前工程", icon='INFO')
        else:
            col.label(text="（队列为空）")


class RTA_PT_queue_run(Panel):
    bl_idname = "RTA_PT_queue_run"
    bl_label = "队列渲染"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "渲染助手"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        s = context.scene.rta
        queue_dir = get_queue_dir()
        count = len(list_blend_files(queue_dir, limit=10000))

        box = layout.box()
        box.label(text="批量渲染", icon='PLAY')

        col = box.column(align=True)
        col.scale_y = 0.8
        if queue_dir:
            col.label(text=queue_dir, icon='FILE_FOLDER')
        else:
            col.label(text="尚未指定队列目录", icon='ERROR')

        box.prop(s, "shutdown_after")

        row = box.row(align=True)
        row.scale_y = 1.5
        row.operator("rta.start_render", text="开始渲染", icon='PLAY')

        row = box.row(align=True)
        row.operator("rta.clear_queue", text="清空队列与脚本", icon='TRASH')

        col = box.column(align=True)
        col.scale_y = 0.75
        if count:
            col.label(text="队列中有 %d 个工程" % count, icon='CHECKMARK')
            col.label(text="点击「开始渲染」自动生成脚本并执行", icon='INFO')
            if s.shutdown_after:
                col.label(text="（渲染完成后将自动关机）", icon='INFO')
        else:
            col.label(text="队列为空，请先添加工程", icon='INFO')


_CLASSES = [
    RTA_Properties,
    RTA_OT_set_queue_dir,
    RTA_OT_add_to_queue,
    RTA_OT_delete_queue_file,
    RTA_OT_delete_other_blends,
    RTA_OT_start_render,
    RTA_OT_clear_queue,
    RTA_PT_main,
    RTA_PT_queue_run,
]


if _ADDON_ID:
    _CLASSES.insert(0, RTA_AddonPreferences)


def register():
    try:
        if hasattr(bpy.types.Scene, "rta"):
            del bpy.types.Scene.rta
    except Exception:
        pass

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.rta = PointerProperty(type=RTA_Properties)


def unregister():
    try:
        if hasattr(bpy.types.Scene, "rta"):
            del bpy.types.Scene.rta
    except Exception:
        pass

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
