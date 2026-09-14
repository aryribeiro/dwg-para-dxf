FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential xz-utils file pkg-config && rm -rf /var/lib/apt/lists/*
COPY src.tar.xz /src.tar.xz
RUN tar xJf /src.tar.xz -C / && cd /libredwg-0.14 \
 && ./configure --disable-bindings --disable-python --disable-docs \
      --disable-shared --enable-static --disable-dependency-tracking \
      --disable-werror --disable-gcov \
      CFLAGS="-O2 -DNDEBUG" LDFLAGS="-static" \
 && make -j1 \
 && strip programs/dwg2dxf programs/dwgread programs/dwg2SVG \
 && mkdir /out && cp programs/dwg2dxf programs/dwgread programs/dwg2SVG /out/ \
 && file /out/* && ls -la /out
