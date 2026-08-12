# Windows 安装与运行

Phoenix Aero Lite 当前交付为内部验证版，支持 Windows x64。SU2 始终作为外部官方程序调用，不会被复制进安装包，也不会自动改用 Fluent。

## 运行前准备

1. 安装官方 SU2 8.5.0 Windows x64 OpenMP 版。
2. 将 `config/local_tools.json` 中的 `su2_cfd_executable` 指向绝对路径；该文件仅保存在本机，不提交 Git。
3. 确认文件名为 `SU2_CFD.exe`，程序启动时会检查路径、版本和 DLL。

也可临时设置用户环境变量 `PAL_SU2_CFD`。本机配置优先于环境变量，含空格路径受支持。

## 从源码运行

```powershell
.\.venv\Scripts\python.exe -m phoenix_aero_lite.app.gui
```

## 生成内部验证包

```powershell
.\scripts\build_windows.ps1
```

构建脚本要求 Windows、项目虚拟环境中的 PyInstaller，以及 `THIRD_PARTY_NOTICES.md`。产物位于 `dist\PhoenixAeroLite`。构建配方不会包含 SU2。

## 故障代码

| 代码 | 含义 |
|---|---|
| `SU2_EXECUTABLE_NOT_CONFIGURED` | 未配置 SU2，且不会回退到 Fluent |
| `SU2_EXECUTABLE_MISSING` | 配置路径不存在 |
| `SU2_VERSION_UNSUPPORTED` | 不是经验证的 SU2 8.5.0 |
| `SU2_DLL_MISSING` | Windows 缺少 DLL 或 VC++ 运行时 |
| `GMSH_VERSION_UNSUPPORTED` | Gmsh Python 包不是 4.15.2 |

## 分发限制

当前打包配方仅用于内部和工程验证。Gmsh、Qt/PySide6 及其传递依赖的最终商业分发，必须先完成许可证与完整许可证文本审查；本说明不构成法律意见。
