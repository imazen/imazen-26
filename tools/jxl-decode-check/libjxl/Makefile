# The libjxl leg of tools/jxl-decode-check, linked statically against a libjxl build: the
# gain-map bundle parser (JxlGainMapReadBundle) lives in libjxl's extras library, which the
# distribution packages leave out. LIBJXL_BUILD is the build directory of the recipe in
# ../README.md; the headers come from it and from the source tree it was configured from.
LIBJXL_BUILD ?= $(HOME)/tmp/libjxl-v012-build
LIBJXL_SRC := $(shell sed -n 's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' $(LIBJXL_BUILD)/CMakeCache.txt)
LIBS := $(LIBJXL_BUILD)/lib/libjxl_extras_nocodec-internal.a $(LIBJXL_BUILD)/lib/libjxl-internal.a

libjxl_hash: libjxl_hash.c $(LIBS)
	$(CC) -O2 -Wall -Wextra -I$(LIBJXL_BUILD)/lib/include -I$(LIBJXL_SRC)/lib/include -c libjxl_hash.c -o libjxl_hash.o
	$(CXX) -o $@ libjxl_hash.o $(LIBS) -L$(LIBJXL_BUILD)/lib -ljxl_cms -Wl,-rpath,$(LIBJXL_BUILD)/lib \
		-lhwy -lbrotlienc -lbrotlidec -lbrotlicommon -llcms2 -lxxhash -lpthread
	rm -f libjxl_hash.o
