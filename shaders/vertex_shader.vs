#version 330 core

layout (location=0) in vec3 position;
layout (location=1) in vec3 tex_coord;
layout (location=2) in float shading_value;

uniform mat4 view_mat;
uniform mat4 proj_mat;

out vec3 interpolated_tex_coords;
out float interpolated_shading_value;

void main()
{
    interpolated_tex_coords = tex_coord;
    interpolated_shading_value = shading_value;
    
    gl_Position = proj_mat * view_mat * vec4(position, 1.0f);
}