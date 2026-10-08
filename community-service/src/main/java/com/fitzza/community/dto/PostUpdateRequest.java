package com.fitzza.community.dto;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fitzza.community.domain.Post;
import com.fitzza.community.domain.PostCategory;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

// 보내지 않은 항목은 그대로 둔다. imageUrl만 null을 보낼 수 있고, 그때는 첨부 이미지를 뗀다.
public class PostUpdateRequest {

    private static final String HAS_TEXT = "(?s).*\\S.*";

    @Size(max = Post.TITLE_MAX_LENGTH, message = "제목은 100자 이하로 입력해주세요.")
    @Pattern(regexp = HAS_TEXT, message = "제목을 입력해주세요.")
    private String title;

    @Size(max = Post.CONTENT_MAX_LENGTH, message = "내용은 5000자 이하로 입력해주세요.")
    @Pattern(regexp = HAS_TEXT, message = "내용을 입력해주세요.")
    private String content;

    private PostCategory category;

    @Size(max = Post.IMAGE_URL_MAX_LENGTH, message = "이미지 주소가 너무 깁니다.")
    private String imageUrl;

    // "보내지 않음"과 "null로 보냄"을 구분하려고 setter가 불렸는지 기록한다.
    private boolean imageUrlSent;

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public PostCategory getCategory() {
        return category;
    }

    public void setCategory(PostCategory category) {
        this.category = category;
    }

    public String getImageUrl() {
        return imageUrl;
    }

    public void setImageUrl(String imageUrl) {
        this.imageUrl = imageUrl;
        this.imageUrlSent = true;
    }

    @JsonIgnore
    public boolean isImageUrlSent() {
        return imageUrlSent;
    }
}
