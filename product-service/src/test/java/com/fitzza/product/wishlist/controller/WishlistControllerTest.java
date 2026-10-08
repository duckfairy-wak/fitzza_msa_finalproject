package com.fitzza.product.wishlist.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fitzza.product.global.constant.ApiHeaders;
import com.fitzza.product.global.dto.PageResponse;
import com.fitzza.product.wishlist.dto.WishlistCheckResponse;
import com.fitzza.product.wishlist.dto.WishlistCreateRequest;
import com.fitzza.product.wishlist.dto.WishlistResponse;
import com.fitzza.product.wishlist.service.WishlistService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(
        controllers = {WishlistController.class, WishlistInternalController.class},
        properties = "spring.cloud.config.enabled=false")
class WishlistControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private WishlistService wishlistService;

    @Test
    void getWishlistsRequiresUserHeader() throws Exception {
        mockMvc.perform(get("/api/wishlists"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void getWishlistsPassesUserAndPagingToService() throws Exception {
        when(wishlistService.findWishlists(eq(1L), eq(0), eq(20)))
                .thenReturn(new PageResponse<>(List.of(), 0, 20, 0, 0, false));

        mockMvc.perform(get("/api/wishlists").header(ApiHeaders.USER_ID, "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.hasNext").value(false));
    }

    @Test
    void addWishlistReturnsExistingOrCreatedItem() throws Exception {
        when(wishlistService.addWishlist(eq(1L), any(WishlistCreateRequest.class)))
                .thenReturn(new WishlistResponse(5L));

        mockMvc.perform(post("/api/wishlists")
                        .header(ApiHeaders.USER_ID, "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"itemId\":\"1\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.wishlistId").value(5));
    }

    @Test
    void addWishlistRejectsBlankItemId() throws Exception {
        mockMvc.perform(post("/api/wishlists")
                        .header(ApiHeaders.USER_ID, "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"itemId\":\" \"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("itemId")));
    }

    @Test
    void removeWishlistReturnsNoContent() throws Exception {
        mockMvc.perform(delete("/api/wishlists")
                        .header(ApiHeaders.USER_ID, "1")
                        .param("itemId", "7"))
                .andExpect(status().isNoContent());

        verify(wishlistService).removeWishlist(1L, "7");
    }

    @Test
    void checkWishlistReturnsOwnership() throws Exception {
        when(wishlistService.checkWishlist(1L, "7")).thenReturn(new WishlistCheckResponse(true));

        mockMvc.perform(get("/internal/v1/wishlists/check")
                        .param("userId", "1")
                        .param("itemId", "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.wishlisted").value(true));
    }

    @Test
    void checkWishlistRequiresAllParameters() throws Exception {
        mockMvc.perform(get("/internal/v1/wishlists/check").param("userId", "1"))
                .andExpect(status().isBadRequest());
    }
}
