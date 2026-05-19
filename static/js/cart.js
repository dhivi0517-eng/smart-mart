document.addEventListener("DOMContentLoaded", function () {

    const buttons = document.querySelectorAll(".btn");

    buttons.forEach(btn => {
        btn.addEventListener("mouseenter", function () {
            btn.style.transform = "scale(1.1)";
        });
        btn.addEventListener("mouseleave", function () {
            btn.style.transform = "scale(1)";
        });
    });

});