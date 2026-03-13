FROM python:3.10-alpine
#1.给Docker引擎找了一个基于python3.10的厨房
WORKDIR /app
#1.在这个厨房里给Docker引擎说，你在这个清理出来的工作台上工作

# 先复制依赖文件并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 再复制项目代码
COPY config/ /app/config/
COPY core/ /app/core/
COPY db/ /app/db/
COPY utils/ /app/utils/
COPY web/ /app/web/
COPY main.py /app/

EXPOSE 8080
CMD [ "python","web/web_dashboard.py" ]
