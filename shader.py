from OpenGL.GL import *
import glm

class ShaderException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Shader:
    def __init__(self, vs_path : str, fs_path : str):
        self._program = None

        def _create_shader(file_path, type):
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
                shader_handle = glCreateShader(type)
                glShaderSource(shader_handle, source)
                glCompileShader(shader_handle)

                success = glGetShaderiv(shader_handle, GL_COMPILE_STATUS)
                if not success:
                    err_info = glGetShaderInfoLog(shader_handle)
                    shader_type = "vs" if type == GL_VERTEX_SHADER else "fs"
                    glDeleteShader(shader_handle)
                    raise ShaderException(f"create shader failed file: {file_path} type: {shader_type} reason: {err_info.decode()}")
                
            return shader_handle


        vs_shader = 0
        fs_shader = 0
        try:
            vs_shader = _create_shader(vs_path, GL_VERTEX_SHADER)
            fs_shader = _create_shader(fs_path, GL_FRAGMENT_SHADER)

            program = glCreateProgram()
            glAttachShader(program, vs_shader)
            glAttachShader(program, fs_shader)
            glLinkProgram(program)

            success = glGetProgramiv(program, GL_LINK_STATUS)
            if not success:
                err_info = glGetProgramInfoLog(program)
                raise ShaderException(f"create program failed vs: {vs_path} fs: {fs_path} reason: {err_info.decode()}")
            
            self._program = program

        except FileNotFoundError:
            raise ShaderException(f"file not found vs{vs_path} fs{fs_path}")
        
        finally:
            if vs_shader > 0:
                glDeleteShader(vs_shader)
            if fs_shader > 0:
                glDeleteShader(fs_shader)


    def use(self):
        if self._program:
            glUseProgram(self._program)

    
    def get_uniform(self, name):
        location = glGetUniformLocation(self._program, name)
        if location < 0:
            raise ShaderException(f"shader has no uniform {name}")
        
        return location


    def set_uniform_mat4f_by_name(self, name, mat4):
        location = self.get_uniform(name)
        glUniformMatrix4fv(location, 1, GL_FALSE, glm.value_ptr(mat4))


    def set_uniform_mat4f_by_loc(self, location, mat4):
        glUniformMatrix4fv(location, 1, GL_FALSE, glm.value_ptr(mat4))
