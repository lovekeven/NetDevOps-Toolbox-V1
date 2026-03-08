FROM python:3.10
#1.给Docker引擎找了一个基于python3.10的厨房
WORKDIR /app
#1.在这个厨房里给Docker引擎说，你在这个清理出来的工作台上工作
COPY requirements.txt /app/
#1.从构建上下文（项目根目录）复制requirements.txt到容器中
#2.构建命令：docker build -f depoly/Dockerfile -t netdevops:v1 .
RUN ls -la /app/ && cat /app/requirements.txt && pip install --no-cache-dir -r requirements.txt
#1.pip理解为python世界里的应用商店下载器，是Python语言里官方包管理工具，pip install + 第三方模块
#2.--no-cache-dir是 pip 的参数，作用是「禁用 pip 缓存，安装完成后自动清理所有安装残留文件」；
#3.-i 是 --index-url 的缩写，指定 pip 下载依赖的「镜像源地址」（不是官方源）
#4.-r 是 --requirement 的缩写，指定 pip 按照「指定文件（requirements.txt）」中的清单，批量安装所有依赖模块
#5.--no-cache-dir、-i、-r → pip 工具的专属参数，作用是给 pip install 命令传递配置，控制 pip 的安装行为，和 Docker 无关
COPY config/ /app/config/
COPY core/ /app/core/
COPY db/ /app/db/
COPY utils/ /app/utils/
COPY web/ /app/web/
COPY main.py /app/
#1.把项目核心目录和文件复制到容器中，保持原有目录结构
#2.构建镜像时需在项目根目录执行：docker build -f depoly/Dockerfile -t netdevops:v1 .
#3.-f 指定Dockerfile路径，最后的.表示构建上下文为当前目录（项目根目录）
EXPOSE 8080
#1.声明容器运行时监听的端口，web_dashboard.py使用8080端口
#2.这只是声明端口，实际端口映射需要在docker run时使用-p参数指定
CMD [ "python","web/web_dashboard.py" ]
#1.容器启动后，自动在 /app 目录下执行 python web/web_dashboard.py 命令（运行你的项目主程序）
#2.在虚拟机本地项目根目录执行 python web/web_dashboard.py启动项目的效果完全一致，只不过这是容器内自动执行的
#3.CMD：Dockerfile 专属指令，核心作用是「指定容器启动时，默认要执行的命令」
