CREATE TABLE user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL
);
CREATE TABLE cccd (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cccd_moi VARCHAR(20),
    cmnd_cu VARCHAR(20),
    ho_ten VARCHAR(100),
    ngay_sinh VARCHAR(20),
    gioi_tinh VARCHAR(10),
    dia_chi TEXT,
    ngay_cap VARCHAR(20),
    user VARCHAR(50),
    img_front VARCHAR(200),
    img_back VARCHAR(200),
    face_img VARCHAR(200),
    UNIQUE (cccd_moi)
);
