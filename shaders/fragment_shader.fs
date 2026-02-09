#version 330 core

uniform sampler2DArray texture_array_sampler;

out vec4 fragment_colour;

in vec3 interpolated_tex_coords;
in float interpolated_shading_value;

void main(void) 
{
	vec4 texture_color =  texture(texture_array_sampler, interpolated_tex_coords);
	if (texture_color.a == 0)
	{
		discard;
	}

	fragment_colour = texture_color * interpolated_shading_value;
}