# 部署有宠相簿

仓库包含应用源码、构建文件与界面素材。**模型资源尚未作为公开发行包提供**，从空目录克隆后不能直接完成识别部署。不要把自己的照片、数据库或含照片路径的训练清单提交到公开仓库。

## 环境与源码

需要 Python 3.11、Node.js 22、FFmpeg / ffprobe，以及 Docker Compose（容器部署时）。GPU 可选；镜像使用 PyTorch 2.6 / CUDA 12.4，需要兼容的 NVIDIA 驱动与 Container Toolkit / CDI。

```bash
git clone https://github.com/0use-TE/OusePet.git
cd OusePet
npm --prefix frontend ci
npm --prefix frontend run build
```

## 模型资源

代码从项目根目录读取下列资源，权重与缓存被 Git 排除。项目暂未发布完整、可直接下载的模型资源包。

| 位置 | 说明 |
| --- | --- |
| `models/yolo11n.pt` | Ultralytics YOLO11n 检测权重 |
| `models/dinov2_vits14_pretrain.pth` | Meta DINOv2 Small ViT-S/14 权重 |
| `.cache/dinov2/` | 官方源码；开发环境提交 `7764ea0f912e53c92e82eb78a2a1631e92725fc8` |
| `models/hedgehog-detector-v1/detector.pt` | 自训练单类刺猬权重，尚未随仓库分发 |
| `models/hedgehog-detector-v1/settings.json` | 对应模型的阈值与输入尺寸 |
| `models/species-verifier-v1/prototypes.npy` | 猫咪与刺猬的 DINOv2 物种参考特征 |
| `models/species-verifier-v1/settings.json` | 对应特征的相似度与差距阈值 |

官方参考：[Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/)、[Meta DINOv2](https://github.com/facebookresearch/dinov2)。核对来源及许可证，不加载未知来源的模型文件。

`scripts/train_hedgehog_detector.py` 和 `scripts/build_species_verifier.py` 记录了开发时的训练／特征生成流程，依赖未公开训练照片和中间报告，不是无需数据的一键安装器。可使用自己的数据重训，并按上表放置兼容资源。

## Docker Compose

先创建运行目录，将照片目录作为绝对路径传入。原文件只读挂载，数据库和缓存写入 `data/`。

```bash
mkdir -p data test-photos
export OUSEPET_PHOTOS=/absolute/path/to/photos
docker compose up -d --build
```

PowerShell 使用 `$env:OUSEPET_PHOTOS='D:/Photos'` 设置路径。`compose.yaml` 默认照片路径保留原开发 NAS 目录，请通过该变量覆盖。启动后在「设置 → 文件夹管理」添加容器内的 `/photos` 或其子目录。

GPU 环境已配置好 CDI 时：

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
```

CPU 模式设置 `OUSEPET_DEVICE=cpu`。构建代理通过 `BUILD_HTTP_PROXY` / `BUILD_HTTPS_PROXY` 传入，不使用开发者的代理地址。

## 本机开发

创建虚拟环境，先安装与硬件适配的 PyTorch / torchvision，再安装 `requirements-album.txt`；参考 [PyTorch 官方说明](https://pytorch.org/get-started/locally/)。准备好模型后：

```bash
python -m venv .venv
# 激活环境，安装 PyTorch / torchvision
python -m pip install -r requirements-album.txt
python -m ousepet.server
```

`ousepet.server` 管理管理端和访客端两个进程。仅开发前端时可以独立运行 `python -m uvicorn ousepet.api:app --host 127.0.0.1 --port 8766` 和 `npm --prefix frontend run dev`。

| 环境变量 | 用途 |
| --- | --- |
| `OUSEPET_DATA` | 数据库、缩略图与缓存，本机默认 `.cache/album` |
| `OUSEPET_LIBRARY_ROOTS` | 允许浏览扫描的根目录，使用当前系统路径分隔符连接 |
| `OUSEPET_DEVICE` | `auto`、`cpu` 或 CUDA 设备 |
| `OUSEPET_CPU_THREADS` | CPU 推理线程数 |
| `OUSEPET_WATCH_INTERVAL` | 增量检查间隔（秒），Compose 默认 60 |

## 回忆分享与反代

- 管理端：`http://NAS-IP:8766`。**没有登录认证，只用于可信网络。**
- 分享端：`http://NAS-IP:8767/s/...`。只提供访客页面和 API，根路径 `/` 返回 404 属正常行为。
- 回忆中创建分享，访客只能看对应回忆。支持提取码、有效期、下载开关；外链列表可关闭或永久删除记录，不影响回忆和原文件。
- 分享设置的域名和外部端口只影响 URL，不自动配置 DNS、端口映射、反代或 HTTPS。

例如 `https://photos.example.com` → HTTPS 反代 → `http://NAS-IP:8767`。外部端口通常为 443，自定义端口应填公网反代实际监听的端口。后端 8767 提供 HTTP，不能直接在其前面拼接 HTTPS。

开启 Cloudflare 常规代理时，外部 HTTPS 使用其[支持的端口](https://developers.cloudflare.com/fundamentals/reference/network-ports/)，如 443、8443，8767 不在列表。反代传正确的 `X-Forwarded-Proto`，使 HTTPS 提取码 cookie 使用 Secure。

关闭下载会禁止原文件下载接口，不阻止保存已加载的预览或截图。照片预览移除 EXIF，视频预览转码并移除来源元数据。

## 备份与更新

备份整个 `data/` 和自行准备的模型，原始照片单独备份。升级前备份数据库，再重新构建前端和镜像；应用内清空识别数据需要确认，不删除只读挂载的原文件。

原开发设备的 fnOS、CUDA 和历史操作记录保留在 [deploy/README.md](../deploy/README.md)，IP、路径和代理都是开发示例，不应直接用于其他设备。
