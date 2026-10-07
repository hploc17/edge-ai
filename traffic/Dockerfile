FROM nvcr.io/nvidia/deepstream-l4t:6.0.1-samples

# 1. Cap nhat va cai dat cac thu vien he thong va build tools
RUN rm -f /etc/apt/sources.list.d/* && \
    apt-get update || true && \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        pkg-config \
        git \
        wget \
        vim \
        python3-pip \
        python3-dev \
        python3-setuptools \
        python3-wheel \
        python3-gi \
        python3-gst-1.0 \
        python3-opencv \
        python3-shapely \
        libglib2.0-dev \
        libgirepository1.0-dev \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Cai dat cac thu vien Python can thiet
RUN pip3 install --no-cache-dir --upgrade setuptools wheel && \
    pip3 install --no-cache-dir paho-mqtt==1.6.1 requests==2.27.1 "psutil==5.9.5" numpy

# 3. Build pyds 1.1.1 tu source (bat buoc cho DeepStream Python)
RUN git clone --branch v1.1.1 --depth 1 \
        https://github.com/NVIDIA-AI-IOT/deepstream_python_apps.git \
        /opt/deepstream_python_apps && \
    cd /opt/deepstream_python_apps/bindings && \
    git submodule update --init && \
    mkdir build && cd build && \
    cmake .. \
        -DPYTHON_MAJOR_VERSION=3 \
        -DPYTHON_MINOR_VERSION=6 \
        -DPIP_PLATFORM=linux_aarch64 \
        -DDS_PATH=/opt/nvidia/deepstream/deepstream && \
    make -j$(nproc) && \
    pip3 install ./pyds-1.1.1-py3-none*.whl && \
    rm -rf /opt/deepstream_python_apps

# 4. Build DeepStream-Yolo custom parser cho YOLO11 (neu can)
WORKDIR /opt/nvidia/deepstream/deepstream/sources
RUN git clone --depth 1 https://github.com/marcoslucianops/DeepStream-Yolo.git || true
WORKDIR /opt/nvidia/deepstream/deepstream/sources/DeepStream-Yolo
ENV CUDA_VER=10.2
RUN make -C nvdsinfer_custom_impl_Yolo || true && \
    cp nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so /opt/nvidia/deepstream/deepstream/lib/ 2>/dev/null || true

# 5. Sao chep ma nguon ung dung va thiet lap moi truong
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8
WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt || true

COPY . /app/
RUN chmod +x /app/*.sh || true

# Khoi chay chuong trinh chinh mac dinh
CMD ["python3", "/app/main.py", "--source-type", "csi", "--sensor-id", "0"]
