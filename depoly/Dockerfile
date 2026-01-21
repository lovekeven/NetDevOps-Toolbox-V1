FROM python:3.10
#1.给Docker引擎找了一个基于python3.10的厨房
WORKDIR /app
#1.在这个厨房里给Dockery引擎说，你在这个清理出来的工作台上工作
COPY requirements.txt /app/ 
#1.COPY的文件必须在项目根目录下面
#2.就是把依赖文件放到了操作台上
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requestrequirequirements.txt
#1.pip理解为python世界里的应用商店下载器，是Python语言里官方包管理工具，pip install + 第三方模块
#2.--no-cache-dir是 pip 的参数，作用是「禁用 pip 缓存，安装完成后自动清理所有安装残留文件」；
#3.-i 是 --index-url 的缩写，指定 pip 下载依赖的「镜像源地址」（不是官方源）
#4.-r 是 --requirement 的缩写，指定 pip 按照「指定文件（requirements.txt）」中的清单，批量安装所有依赖模块
#5.--no-cache-dir、-i、-r → pip 工具的专属参数，作用是给 pip install 命令传递配置，控制 pip 的安装行为，和 Docker 无关
COPY . /app/
#把蛋糕胚，也就是这个项目根目录下面所有的文件（.），放到操作台上给厨师操作（/app/）,让他结合刚买来的调料
CMD [ "python","web_dashboard.py" ]
#1.容器启动后，自动在 /app 目录下执行 python web_dashboard.py 命令（运行你的项目主程序）
#2.在虚拟机本地项目根目录执行 python web_dashboard.py启动项目的效果完全一致，只不过这是容器内自动执行的
#3.CMD：Dockerfile 专属指令，核心作用是「指定容器启动时，默认要执行的命令」
