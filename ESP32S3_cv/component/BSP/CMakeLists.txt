set(src_dirs
            LED)

set(include_directories 
                    LED)

set(requires

        driver)

idf_component_register(SRC_DIRS ${SRC_DIRS} INCLUDE_DIRS ${include_dirs} REQUIRES ${requires})
component_compile_options(-ffast-math -O3 -Wno-error=format)