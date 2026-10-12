SELECT p.post_id, p.board_id
FROM posts p
LEFT JOIN boards b ON b.board_id=p.board_id
WHERE p.board_id IS NOT NULL AND b.board_id IS NULL;

SELECT c.comment_id, c.post_id
FROM comments c
LEFT JOIN posts p ON p.post_id=c.post_id
WHERE p.post_id IS NULL;

SELECT i.image_id, i.post_id
FROM post_images i
LEFT JOIN posts p ON p.post_id=i.post_id
WHERE p.post_id IS NULL;
