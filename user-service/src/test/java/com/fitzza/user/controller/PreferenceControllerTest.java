package com.fitzza.user.controller;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class PreferenceControllerTest {

    private final MockMvc mockMvc = MockMvcBuilders.standaloneSetup(new PreferenceController()).build();

    @ParameterizedTest
    @ValueSource(strings = {"/users/preferences/fits", "/api/users/preferences/fits"})
    void getFitsReturnsOrderedLabelsAndValues(String path) throws Exception {
        mockMvc.perform(get(path))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(content().json("""
                        [
                          {"label":"레귤러","value":"REGULAR"},
                          {"label":"릴렉스드","value":"RELAXED"},
                          {"label":"슬림","value":"SLIM"},
                          {"label":"오버사이즈","value":"OVERSIZED"},
                          {"label":"크롭","value":"CROPPED"}
                        ]
                        """, true));
    }

    @ParameterizedTest
    @ValueSource(strings = {"/users/preferences/styles", "/api/users/preferences/styles"})
    void getStylesReturnsOrderedLabelsAndValues(String path) throws Exception {
        mockMvc.perform(get(path))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(content().json("""
                        [
                          {"label":"캐주얼","value":"CASUAL"},
                          {"label":"미니멀","value":"MINIMAL"},
                          {"label":"스트릿","value":"STREET"},
                          {"label":"포멀","value":"FORMAL"},
                          {"label":"스포티","value":"SPORTY"},
                          {"label":"빈티지","value":"VINTAGE"}
                        ]
                        """, true));
    }
}
