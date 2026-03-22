---
title: "{{ replace .Name "-" " " | title }}"
date: {{ .Date }}
slug: "{{ .Name }}"
description: ""
image: ""
image_caption: ""
categories: []
tags: []
draft: true
---

<!-- 
  Bilder einbinden:
  
  Volles Breitenbild:
  ![Beschreibung](bild.jpg)
  
  Mit Bildunterschrift:
  {{</* figure src="bild.jpg" caption="Beschreibung" */>}}
  
  Video einbetten:
  <video controls><source src="video.mp4" type="video/mp4"></video>
-->
