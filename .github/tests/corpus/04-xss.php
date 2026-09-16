<?php
class pluginXss extends Plugin {
	public function siteHead() { echo "<meta name='q' content='".$_GET['q']."'>"; }
}
